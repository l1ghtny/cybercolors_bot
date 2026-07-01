import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import modal

APP_NAME = os.getenv("MODAL_APP_NAME") or "cybercolors-youtube-transcription"
MODEL_NAME = os.getenv("WHISPER_MODEL_NAME") or "openai/whisper-large-v3"
MODEL_REVISION = os.getenv("WHISPER_MODEL_REVISION") or None
MODEL_DIR = "/model"

TRANSCRIBE_TIMEOUT_SECONDS = int(os.getenv("MODAL_WHISPER_TIMEOUT_SECONDS") or "1800")
TRANSCRIBE_GPU = os.getenv("MODAL_WHISPER_GPU") or "T4"
TRANSCRIBE_MAX_CONTAINERS = int(os.getenv("MODAL_WHISPER_MAX_CONTAINERS") or "1")
TRANSCRIBE_SCALEDOWN_WINDOW = int(os.getenv("MODAL_WHISPER_SCALEDOWN_WINDOW") or "30")
TRANSCRIBE_CHUNK_LENGTH_SECONDS = int(os.getenv("WHISPER_CHUNK_LENGTH_SECONDS") or "30")
TRANSCRIBE_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE") or "4")
TRANSCRIBE_LANGUAGE = os.getenv("WHISPER_LANGUAGE") or None

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .uv_pip_install(
        "accelerate>=0.26.0",
        "hf-transfer>=0.1.8",
        "librosa>=0.10.0",
        "soundfile>=0.12.1",
        "torch>=2.2.0",
        "transformers>=4.41.0",
        "yt-dlp>=2026.6.9",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HUB_CACHE": MODEL_DIR,
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
            result = self.pipeline(
                str(audio_path),
                batch_size=TRANSCRIBE_BATCH_SIZE,
                chunk_length_s=TRANSCRIBE_CHUNK_LENGTH_SECONDS,
                return_timestamps=True,
                generate_kwargs=generate_kwargs,
            )
            audio_file_name = audio_path.name
            audio_size_bytes = audio_path.stat().st_size

        chunks = result.get("chunks") or []
        segments = [
            {
                "start": _timestamp_start(chunk.get("timestamp")),
                "end": _timestamp_end(chunk.get("timestamp")),
                "text": str(chunk.get("text") or "").strip(),
            }
            for chunk in chunks
            if str(chunk.get("text") or "").strip()
        ]
        text = str(result.get("text") or " ".join(segment["text"] for segment in segments)).strip()
        return {
            "text": text,
            "language": selected_language,
            "model": MODEL_NAME,
            "source_url": source_url,
            "content_type": content_type,
            "audio_file": audio_file_name,
            "audio_size_bytes": audio_size_bytes,
            "metadata": metadata or {},
            "segments_count": len(segments),
            "segments": segments,
        }


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

    output_template = str(temp_dir / "audio_%(id)s.%(ext)s")
    options = {
        "format": os.getenv("YOUTUBE_AUDIO_FORMAT") or "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": os.getenv("YOUTUBE_AUDIO_CODEC") or "mp3",
                "preferredquality": os.getenv("YOUTUBE_AUDIO_QUALITY") or "192",
            }
        ],
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        downloader.extract_info(youtube_url, download=True)
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
