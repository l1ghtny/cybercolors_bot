import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

import modal


logger = logging.getLogger(__name__)

APP_NAME = os.getenv("MODAL_APP_NAME") or "cybercolors-youtube-transcription"
MODEL_NAME = os.getenv("WHISPER_MODEL_NAME") or "openai/whisper-large-v3"
MODEL_REVISION = os.getenv("WHISPER_MODEL_REVISION") or None
MODEL_DIR = "/model"

TRANSCRIBE_TIMEOUT_SECONDS = int(os.getenv("MODAL_WHISPER_TIMEOUT_SECONDS") or "1800")
TRANSCRIBE_GPU = os.getenv("MODAL_WHISPER_GPU") or "T4"
TRANSCRIBE_MAX_CONTAINERS = int(os.getenv("MODAL_WHISPER_MAX_CONTAINERS") or "1")
TRANSCRIBE_SCALEDOWN_WINDOW = int(os.getenv("MODAL_WHISPER_SCALEDOWN_WINDOW") or "30")
TRANSCRIBE_LANGUAGE = os.getenv("WHISPER_LANGUAGE") or None
VAD_SAMPLE_RATE = 16_000
VAD_LEADING_PADDING_SECONDS = 0.25
VAD_TRAILING_PADDING_SECONDS = 1.0
VAD_MIN_TRIM_SECONDS = 0.5

_TRAILING_SUBTITLE_CREDITS_RE = re.compile(
    r"\s*Редактор\s+субтитров\s+[А-ЯЁA-Z]\.?\s*[А-ЯЁA-Z][А-ЯЁа-яёA-Za-z-]+"
    r"\s+Корректор\s+[А-ЯЁA-Z]\.?\s*[А-ЯЁA-Z][А-ЯЁа-яёA-Za-z-]+\s*[.!]?\s*$",
    re.IGNORECASE,
)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl", "ffmpeg", "unzip")
    .run_commands(
        "curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s v2.8.1",
    )
    .uv_pip_install(
        "accelerate>=0.26.0",
        "hf-transfer>=0.1.8",
        "librosa>=0.10.0",
        "silero-vad==6.2.1",
        "soundfile>=0.12.1",
        "torch>=2.2.0",
        "transformers==5.14.1",
        "yt-dlp[default]>=2026.7.4",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HUB_CACHE": MODEL_DIR,
            "DENO_NO_UPDATE_CHECK": "1",
        }
    )
)

model_cache = modal.Volume.from_name("cybercolors-whisper-model-cache", create_if_missing=True)
app = modal.App(APP_NAME, image=image, volumes={MODEL_DIR: model_cache})


@app.function(timeout=1800)
def download_model() -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        MODEL_NAME,
        revision=MODEL_REVISION,
        local_dir=MODEL_DIR,
        ignore_patterns=["*.bin", "*.onnx"],
    )
    model_cache.commit()


@app.cls(
    gpu=TRANSCRIBE_GPU,
    timeout=TRANSCRIBE_TIMEOUT_SECONDS,
    max_containers=TRANSCRIBE_MAX_CONTAINERS,
    scaledown_window=TRANSCRIBE_SCALEDOWN_WINDOW,
)
class YouTubeWhisperTranscriber:
    @modal.enter()
    def load_model(self) -> None:
        import torch
        from silero_vad import load_silero_vad
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

        torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            MODEL_NAME,
            revision=MODEL_REVISION,
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=True,
            use_safetensors=True,
            cache_dir=MODEL_DIR,
        )
        model.to(device)
        processor = AutoProcessor.from_pretrained(
            MODEL_NAME,
            revision=MODEL_REVISION,
            cache_dir=MODEL_DIR,
        )
        self.pipeline = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            torch_dtype=torch_dtype,
            device=device,
        )
        self.vad_model = load_silero_vad()

    @modal.method()
    def transcribe_audio(
        self,
        *,
        audio_bytes: bytes = b"",
        filename: str = "",
        content_type: str = "",
        youtube_url: str = "",
        max_audio_bytes: int = 0,
        source_url: str = "",
        metadata: dict[str, Any] | None = None,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> dict[str, Any]:
        generate_kwargs: dict[str, Any] = {"task": "transcribe"}
        selected_language = language or TRANSCRIBE_LANGUAGE
        if selected_language:
            generate_kwargs["language"] = selected_language
        if initial_prompt:
            generate_kwargs["prompt"] = initial_prompt

        with tempfile.TemporaryDirectory(prefix="cybercolors_modal_audio_") as temp_dir:
            audio_path = _materialize_audio(
                temp_dir=Path(temp_dir),
                audio_bytes=audio_bytes,
                filename=filename,
                youtube_url=youtube_url,
                max_audio_bytes=max_audio_bytes,
            )
            audio_input, audio_preprocessing = _prepare_audio_for_transcription(
                audio_path=audio_path,
                vad_model=self.vad_model,
            )
            result = _run_whisper_pipeline(
                pipeline=self.pipeline,
                audio_path=audio_input,
                generate_kwargs=generate_kwargs,
            )
            audio_file_name = audio_path.name
            audio_size_bytes = audio_path.stat().st_size

        chunks = result.get("chunks") or []
        timestamp_offset = float(audio_preprocessing.get("speech_start_seconds") or 0.0)
        segments = [
            {
                "start": _offset_timestamp(_timestamp_start(chunk.get("timestamp")), timestamp_offset),
                "end": _offset_timestamp(_timestamp_end(chunk.get("timestamp")), timestamp_offset),
                "text": str(chunk.get("text") or "").strip(),
            }
            for chunk in chunks
            if str(chunk.get("text") or "").strip()
        ]
        segments = _strip_trailing_hallucination_from_segments(segments)
        text = _strip_trailing_transcription_hallucination(
            str(result.get("text") or " ".join(segment["text"] for segment in segments)).strip()
        )
        return {
            "text": text,
            "language": _detected_language(result, selected_language=selected_language),
            "model": MODEL_NAME,
            "source_url": source_url,
            "content_type": content_type,
            "audio_file": audio_file_name,
            "audio_size_bytes": audio_size_bytes,
            "metadata": metadata or {},
            "segments_count": len(segments),
            "segments": segments,
            "audio_preprocessing": audio_preprocessing,
        }


def _run_whisper_pipeline(
    *,
    pipeline: Any,
    audio_path: Any,
    generate_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Use Whisper's native sequential long-form generation.

    Passing ``chunk_length_s`` makes the generic ASR pipeline split audio into
    experimental fixed chunks. Without it, the Whisper pipeline passes the
    complete, untruncated features to ``model.generate`` and uses Whisper's
    timestamp-based long-form algorithm.
    """
    pipeline_input = str(audio_path) if isinstance(audio_path, Path) else audio_path
    return pipeline(
        pipeline_input,
        return_timestamps=True,
        return_language=True,
        generate_kwargs=generate_kwargs,
    )


def _prepare_audio_for_transcription(*, audio_path: Path, vad_model: Any) -> tuple[Any, dict[str, Any]]:
    import librosa
    import torch
    from silero_vad import get_speech_timestamps

    try:
        waveform, _sampling_rate = librosa.load(str(audio_path), sr=VAD_SAMPLE_RATE, mono=True)
        total_samples = len(waveform)
        speech_timestamps = get_speech_timestamps(
            torch.from_numpy(waveform),
            vad_model,
            sampling_rate=VAD_SAMPLE_RATE,
            min_silence_duration_ms=500,
            speech_pad_ms=250,
        )
        trim_start, trim_end = _speech_trim_bounds(
            speech_timestamps,
            total_samples=total_samples,
            sampling_rate=VAD_SAMPLE_RATE,
        )
    except Exception as exc:
        logger.exception("modal_audio_vad_failed audio_file=%s", audio_path.name)
        return audio_path, {"vad_applied": False, "fallback_reason": type(exc).__name__}

    duration_seconds = total_samples / VAD_SAMPLE_RATE if total_samples else 0.0
    speech_start_seconds = trim_start / VAD_SAMPLE_RATE
    speech_end_seconds = trim_end / VAD_SAMPLE_RATE
    leading_trim_seconds = speech_start_seconds
    trailing_trim_seconds = max(0.0, duration_seconds - speech_end_seconds)
    preprocessing = {
        "vad_applied": bool(speech_timestamps),
        "audio_duration_seconds": round(duration_seconds, 3),
        "speech_start_seconds": round(speech_start_seconds, 3),
        "speech_end_seconds": round(speech_end_seconds, 3),
        "leading_trim_seconds": round(leading_trim_seconds, 3),
        "trailing_trim_seconds": round(trailing_trim_seconds, 3),
    }
    if not speech_timestamps or max(leading_trim_seconds, trailing_trim_seconds) < VAD_MIN_TRIM_SECONDS:
        return audio_path, preprocessing

    logger.info(
        "modal_audio_vad_trimmed audio_file=%s duration_seconds=%.3f leading_trim_seconds=%.3f trailing_trim_seconds=%.3f",
        audio_path.name,
        duration_seconds,
        leading_trim_seconds,
        trailing_trim_seconds,
    )
    return {"array": waveform[trim_start:trim_end], "sampling_rate": VAD_SAMPLE_RATE}, preprocessing


def _speech_trim_bounds(
    speech_timestamps: list[dict[str, Any]],
    *,
    total_samples: int,
    sampling_rate: int,
) -> tuple[int, int]:
    if not speech_timestamps or total_samples <= 0:
        return 0, max(0, total_samples)

    leading_padding = round(VAD_LEADING_PADDING_SECONDS * sampling_rate)
    trailing_padding = round(VAD_TRAILING_PADDING_SECONDS * sampling_rate)
    first_speech_sample = int(speech_timestamps[0]["start"])
    last_speech_sample = int(speech_timestamps[-1]["end"])
    return (
        max(0, first_speech_sample - leading_padding),
        min(total_samples, last_speech_sample + trailing_padding),
    )


def _strip_trailing_transcription_hallucination(text: str) -> str:
    return _TRAILING_SUBTITLE_CREDITS_RE.sub("", text or "").strip()


def _strip_trailing_hallucination_from_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not segments:
        return segments
    cleaned_text = _strip_trailing_transcription_hallucination(str(segments[-1].get("text") or ""))
    if cleaned_text == str(segments[-1].get("text") or "").strip():
        return segments
    if cleaned_text:
        return [*segments[:-1], {**segments[-1], "text": cleaned_text}]
    return segments[:-1]


def _detected_language(result: dict[str, Any], *, selected_language: str | None) -> str | None:
    if selected_language:
        return selected_language

    top_level_language = result.get("language")
    if isinstance(top_level_language, str) and top_level_language.strip():
        return top_level_language.strip()

    detected_languages = [
        language.strip()
        for chunk in result.get("chunks") or []
        if isinstance(chunk, dict)
        and isinstance((language := chunk.get("language")), str)
        and language.strip()
    ]
    if not detected_languages:
        return None

    normalized_counts = Counter(language.casefold() for language in detected_languages)
    most_common_language = normalized_counts.most_common(1)[0][0]
    return next(language for language in detected_languages if language.casefold() == most_common_language)


def _materialize_audio(
    *,
    temp_dir: Path,
    audio_bytes: bytes,
    filename: str,
    youtube_url: str,
    max_audio_bytes: int,
) -> Path:
    if audio_bytes:
        suffix = Path(filename or "audio.webm").suffix or ".webm"
        audio_path = temp_dir / f"audio{suffix}"
        audio_path.write_bytes(audio_bytes)
        if max_audio_bytes and audio_path.stat().st_size > max_audio_bytes:
            raise ValueError(f"Audio is too large for transcription. Limit is {max_audio_bytes} bytes.")
        return _normalize_audio(audio_path, temp_dir=temp_dir)
    elif youtube_url:
        audio_path = _download_youtube_audio(youtube_url=youtube_url, temp_dir=temp_dir)
    else:
        raise ValueError("Either audio_bytes or youtube_url is required.")

    if max_audio_bytes and audio_path.stat().st_size > max_audio_bytes:
        raise ValueError(f"Audio is too large for transcription. Limit is {max_audio_bytes} bytes.")
    return audio_path


def _download_youtube_audio(*, youtube_url: str, temp_dir: Path) -> Path:
    import yt_dlp

    try:
        ejs_version = importlib_metadata.version("yt-dlp-ejs")
    except importlib_metadata.PackageNotFoundError:
        ejs_version = None
    logger.info(
        "modal_youtube_download_started yt_dlp_version=%s yt_dlp_ejs_version=%s deno_available=%s",
        importlib_metadata.version("yt-dlp"),
        ejs_version,
        shutil.which("deno") is not None,
    )
    output_template = str(temp_dir / "audio_%(id)s.%(ext)s")
    options = {
        "format": os.getenv("YOUTUBE_AUDIO_FORMAT") or "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": False,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": os.getenv("YOUTUBE_AUDIO_CODEC") or "mp3",
                "preferredquality": os.getenv("YOUTUBE_AUDIO_QUALITY") or "192",
            }
        ],
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(youtube_url, download=True)
    except Exception as exc:
        logger.exception("modal_youtube_download_failed")
        message = str(exc).lower()
        if any(marker in message for marker in ("not a bot", "confirm you", "cookies", "ip has been blocked")):
            raise RuntimeError("YouTube bot access challenge while downloading audio") from None
        raise RuntimeError(f"YouTube audio download failed: {type(exc).__name__}") from None
    logger.info(
        "modal_youtube_download_completed video_id=%s duration=%s",
        info.get("id") if isinstance(info, dict) else None,
        info.get("duration") if isinstance(info, dict) else None,
    )
    candidates = sorted(
        [item for item in temp_dir.glob("audio_*") if item.is_file()],
        key=lambda item: (_audio_candidate_rank(item), -item.stat().st_size, item.name),
    )
    if not candidates:
        raise ValueError("No YouTube audio file was downloaded.")
    return _normalize_audio(candidates[0], temp_dir=temp_dir)


def _audio_candidate_rank(path: Path) -> int:
    preferred_suffixes = {
        ".mp3": 0,
        ".m4a": 1,
        ".wav": 2,
        ".flac": 3,
        ".ogg": 4,
        ".opus": 5,
        ".webm": 6,
    }
    return preferred_suffixes.get(path.suffix.lower(), 99)


def _normalize_audio(path: Path, *, temp_dir: Path) -> Path:
    normalized_path = temp_dir / "audio_normalized.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(normalized_path),
        ],
        check=True,
    )
    if not normalized_path.exists() or normalized_path.stat().st_size == 0:
        raise ValueError("Audio normalization produced an empty file.")
    return normalized_path


def _timestamp_start(timestamp: Any) -> float | None:
    if isinstance(timestamp, (list, tuple)) and timestamp:
        value = timestamp[0]
        return float(value) if value is not None else None
    return None


def _timestamp_end(timestamp: Any) -> float | None:
    if isinstance(timestamp, (list, tuple)) and len(timestamp) > 1:
        value = timestamp[1]
        return float(value) if value is not None else None
    return None


def _offset_timestamp(value: float | None, offset: float) -> float | None:
    return value + offset if value is not None else None
