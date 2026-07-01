import hashlib
import html
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

KNOWLEDGE_UPLOAD_ROOT = Path(os.getenv("AI_KNOWLEDGE_UPLOAD_ROOT") or Path("logs") / "ai_knowledge_uploads")
MAX_KNOWLEDGE_UPLOAD_BYTES = int(os.getenv("AI_KNOWLEDGE_MAX_UPLOAD_BYTES") or str(10 * 1024 * 1024))
MAX_EXTRACTED_TEXT_CHARS = int(os.getenv("AI_KNOWLEDGE_MAX_EXTRACTED_TEXT_CHARS") or "500000")
YOUTUBE_TRANSCRIPTION_PROVIDER = (os.getenv("AI_YOUTUBE_TRANSCRIPTION_PROVIDER") or "modal").strip().lower()
YOUTUBE_AUDIO_MAX_BYTES = int(os.getenv("AI_YOUTUBE_AUDIO_MAX_BYTES") or str(250 * 1024 * 1024))
YOUTUBE_AUDIO_FORMAT = os.getenv("AI_YOUTUBE_AUDIO_FORMAT") or "bestaudio/best"
YOUTUBE_CAPTION_LANGUAGES = [
    item.strip()
    for item in (os.getenv("AI_YOUTUBE_CAPTION_LANGUAGES") or "en").split(",")
    if item.strip()
]
TRANSCRIPTION_TIMEOUT_SECONDS = int(os.getenv("AI_YOUTUBE_TRANSCRIPTION_TIMEOUT_SECONDS") or "900")
MODAL_TRANSCRIPTION_APP_NAME = os.getenv("AI_YOUTUBE_TRANSCRIPTION_MODAL_APP_NAME") or "cybercolors-youtube-transcription"
MODAL_TRANSCRIPTION_CALLABLE_TYPE = (os.getenv("AI_YOUTUBE_TRANSCRIPTION_MODAL_CALLABLE_TYPE") or "class").strip().lower()
MODAL_TRANSCRIPTION_CLASS_NAME = os.getenv("AI_YOUTUBE_TRANSCRIPTION_MODAL_CLASS_NAME") or "YouTubeWhisperTranscriber"
MODAL_TRANSCRIPTION_METHOD_NAME = os.getenv("AI_YOUTUBE_TRANSCRIPTION_MODAL_METHOD_NAME") or "transcribe_audio"
MODAL_TRANSCRIPTION_FUNCTION_NAME = os.getenv("AI_YOUTUBE_TRANSCRIPTION_MODAL_FUNCTION_NAME") or "transcribe_audio"
MODAL_TRANSCRIPTION_ENVIRONMENT = os.getenv("AI_YOUTUBE_TRANSCRIPTION_MODAL_ENVIRONMENT") or None
_modal_version = os.getenv("AI_YOUTUBE_TRANSCRIPTION_MODAL_VERSION")
MODAL_TRANSCRIPTION_VERSION = int(_modal_version) if _modal_version else None

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".log",
    ".html",
    ".htm",
}
TEXT_MIME_PREFIXES = ("text/",)
TEXT_MIME_TYPES = {
    "application/json",
    "application/x-ndjson",
    "application/yaml",
    "application/xml",
    "application/csv",
}

_TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?[\d.,]*\s+-->\s+")
_WEBVTT_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class KnowledgeImportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def safe_knowledge_upload_key(server_id: int, source_id: Any, filename: str) -> str:
    suffix = Path(filename or "upload").suffix.lower()[:20]
    safe_suffix = re.sub(r"[^a-z0-9.]+", "", suffix) or ".bin"
    return f"{int(server_id)}_{source_id}{safe_suffix}"


def store_knowledge_upload(
    *,
    server_id: int,
    source_id: Any,
    filename: str,
    payload: bytes,
    root: Path = KNOWLEDGE_UPLOAD_ROOT,
) -> dict[str, Any]:
    if not payload:
        raise KnowledgeImportError("empty_file", "Uploaded file is empty.")
    if len(payload) > MAX_KNOWLEDGE_UPLOAD_BYTES:
        raise KnowledgeImportError(
            "file_too_large",
            f"Uploaded file is too large. Limit is {MAX_KNOWLEDGE_UPLOAD_BYTES} bytes.",
        )

    key = safe_knowledge_upload_key(server_id, source_id, filename)
    root.mkdir(parents=True, exist_ok=True)
    path = root / key
    path.write_bytes(payload)
    return {
        "storage_key": key,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def knowledge_upload_path(storage_key: str, root: Path = KNOWLEDGE_UPLOAD_ROOT) -> Path:
    if "/" in storage_key or "\\" in storage_key:
        raise KnowledgeImportError("invalid_storage_key", "Invalid knowledge upload storage key.")
    return root / storage_key


def extract_text_from_file(
    *,
    storage_key: str,
    mime_type: str | None,
    filename: str | None = None,
    root: Path = KNOWLEDGE_UPLOAD_ROOT,
) -> tuple[str, dict[str, Any]]:
    path = knowledge_upload_path(storage_key, root=root)
    if not path.exists():
        raise KnowledgeImportError("file_not_found", "Uploaded file was not found on disk.")

    suffix = (Path(filename or path.name).suffix or path.suffix).lower()
    normalized_mime = (mime_type or "").lower().split(";")[0].strip()
    payload = path.read_bytes()

    if suffix == ".pdf" or normalized_mime == "application/pdf":
        text = _extract_pdf_text(path)
        parser = "pypdf"
    elif suffix == ".docx" or normalized_mime.endswith("wordprocessingml.document"):
        text = _extract_docx_text(path)
        parser = "docx-xml"
    elif _is_text_like(suffix=suffix, mime_type=normalized_mime):
        text = _decode_text(payload)
        parser = "plain-text"
    else:
        raise KnowledgeImportError(
            "unsupported_file_type",
            "Unsupported knowledge file type. Supported types: text, markdown, CSV, JSON, PDF, DOCX.",
        )

    text = _bounded_text(text)
    if not text:
        raise KnowledgeImportError("empty_extraction", "No readable text was extracted from the uploaded file.")
    return text, {
        "parser": parser,
        "source_filename": filename,
        "extracted_chars": len(text),
    }


def extract_text_from_youtube_url(url: str) -> tuple[str, dict[str, Any]]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise KnowledgeImportError("yt_dlp_missing", "yt-dlp is required for YouTube imports.") from exc

    with tempfile.TemporaryDirectory(prefix="cybercolors_youtube_") as temp_dir:
        output_template = str(Path(temp_dir) / "%(id)s.%(ext)s")
        options = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": YOUTUBE_CAPTION_LANGUAGES,
            "subtitlesformat": "vtt/best",
            "outtmpl": output_template,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
        except Exception as exc:
            raise KnowledgeImportError("youtube_fetch_failed", f"Could not fetch YouTube metadata/captions: {exc}") from exc

        caption_files = _select_caption_files(Path(temp_dir))
        if not caption_files:
            return _extract_youtube_audio_and_transcribe(url=url, info=info, temp_dir=Path(temp_dir))

        caption_path = caption_files[0]
        raw_caption = _decode_text(caption_path.read_bytes())
        text = _bounded_text(_clean_caption_text(raw_caption))
        if not text:
            raise KnowledgeImportError("empty_extraction", "No readable text was extracted from YouTube captions.")

        return text, {
            "provider": "yt-dlp",
            "mode": "captions",
            "video_id": info.get("id"),
            "video_title": info.get("title"),
            "duration": info.get("duration"),
            "webpage_url": info.get("webpage_url") or url,
            "caption_file": caption_path.name,
            "caption_ext": caption_path.suffix.lower().lstrip("."),
            "extracted_chars": len(text),
        }


def _extract_youtube_audio_and_transcribe(
    *,
    url: str,
    info: dict[str, Any],
    temp_dir: Path,
) -> tuple[str, dict[str, Any]]:
    if YOUTUBE_TRANSCRIPTION_PROVIDER != "modal":
        raise KnowledgeImportError(
            "youtube_captions_missing",
            f"No YouTube captions were available and transcription provider {YOUTUBE_TRANSCRIPTION_PROVIDER!r} is not supported.",
        )

    source_url = info.get("webpage_url") or url
    source_metadata = {
        "video_id": info.get("id"),
        "video_title": info.get("title"),
        "duration": info.get("duration"),
    }
    provider = ModalTranscriptionProvider()
    try:
        transcription = provider.transcribe_youtube(
            youtube_url=url,
            source_url=source_url,
            source_metadata=source_metadata,
        )
        fallback_mode = "modal_youtube"
    except KnowledgeImportError as exc:
        if not _should_retry_youtube_transcription_with_local_audio(exc):
            raise
        audio_path = _download_youtube_audio(url=url, temp_dir=temp_dir)
        transcription = provider.transcribe(
            audio_path=audio_path,
            source_url=source_url,
            source_metadata={**source_metadata, "modal_youtube_error": str(exc)},
        )
        fallback_mode = "local_audio_upload"
    text = _bounded_text(transcription["text"])
    if not text:
        raise KnowledgeImportError("empty_transcription", "Modal transcription returned no readable text.")

    return text, {
        "provider": "modal",
        "mode": "audio_transcription",
        "video_id": info.get("id"),
        "video_title": info.get("title"),
        "duration": info.get("duration"),
        "webpage_url": source_url,
        "fallback_mode": fallback_mode,
        "language": transcription.get("language"),
        "transcription_model": transcription.get("model"),
        "segments_count": transcription.get("segments_count"),
        "extracted_chars": len(text),
    }


def _download_youtube_audio(*, url: str, temp_dir: Path) -> Path:
    try:
        import yt_dlp
    except ImportError as exc:
        raise KnowledgeImportError("yt_dlp_missing", "yt-dlp is required for YouTube imports.") from exc

    audio_template = str(temp_dir / "audio_%(id)s.%(ext)s")
    options = {
        "format": YOUTUBE_AUDIO_FORMAT,
        "outtmpl": audio_template,
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.extract_info(url, download=True)
    except Exception as exc:
        raise KnowledgeImportError("youtube_audio_download_failed", f"Could not download YouTube audio: {exc}") from exc

    candidates = sorted(
        [item for item in temp_dir.glob("audio_*") if item.is_file()],
        key=lambda item: item.stat().st_size,
        reverse=True,
    )
    if not candidates:
        raise KnowledgeImportError("youtube_audio_missing", "No YouTube audio file was downloaded.")
    return candidates[0]


def _should_retry_youtube_transcription_with_local_audio(exc: KnowledgeImportError) -> bool:
    message = str(exc).lower()
    return (
        exc.code == "modal_transcription_failed"
        and "youtube" in message
        and any(marker in message for marker in ("sign in", "not a bot", "cookies", "bot"))
    )


def _select_caption_files(temp_dir: Path) -> list[Path]:
    candidates = [
        item
        for item in temp_dir.glob("*.*")
        if item.is_file() and item.suffix.lower() in {".vtt", ".srt", ".ttml", ".srv1", ".srv2", ".srv3"}
    ]

    def priority(path: Path) -> tuple[int, int, int]:
        name = path.name.lower()
        language_rank = len(YOUTUBE_CAPTION_LANGUAGES)
        for index, language in enumerate(YOUTUBE_CAPTION_LANGUAGES):
            normalized = language.lower()
            if f".{normalized}." in name or f".{normalized}-" in name or f".{normalized}_" in name:
                language_rank = index
                break
        return (language_rank, -path.stat().st_size, len(name))

    return sorted(candidates, key=priority)


class ModalTranscriptionProvider:
    def __init__(
        self,
        *,
        app_name: str = MODAL_TRANSCRIPTION_APP_NAME,
        callable_type: str = MODAL_TRANSCRIPTION_CALLABLE_TYPE,
        class_name: str = MODAL_TRANSCRIPTION_CLASS_NAME,
        method_name: str = MODAL_TRANSCRIPTION_METHOD_NAME,
        function_name: str = MODAL_TRANSCRIPTION_FUNCTION_NAME,
        environment_name: str | None = MODAL_TRANSCRIPTION_ENVIRONMENT,
        version: int | None = MODAL_TRANSCRIPTION_VERSION,
        timeout_seconds: int = TRANSCRIPTION_TIMEOUT_SECONDS,
        remote_handle: Any | None = None,
    ) -> None:
        self.app_name = app_name.strip()
        self.callable_type = callable_type.strip().lower()
        self.class_name = class_name.strip()
        self.method_name = method_name.strip()
        self.function_name = function_name.strip()
        self.environment_name = environment_name.strip() if environment_name else None
        self.version = version
        self.timeout_seconds = timeout_seconds
        self._remote_handle = remote_handle

    def transcribe(
        self,
        *,
        audio_path: Path,
        source_url: str,
        source_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return self._transcribe_remote(
            audio_bytes=audio_path.read_bytes(),
            filename=audio_path.name,
            content_type=_audio_content_type(audio_path),
            youtube_url=None,
            source_url=source_url,
            source_metadata=source_metadata,
        )

    def transcribe_youtube(
        self,
        *,
        youtube_url: str,
        source_url: str,
        source_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return self._transcribe_remote(
            audio_bytes=None,
            filename=None,
            content_type=None,
            youtube_url=youtube_url,
            source_url=source_url,
            source_metadata=source_metadata,
        )

    def _transcribe_remote(
        self,
        *,
        audio_bytes: bytes | None,
        filename: str | None,
        content_type: str | None,
        youtube_url: str | None,
        source_url: str,
        source_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.app_name:
            raise KnowledgeImportError(
                "modal_transcription_not_configured",
                "AI_YOUTUBE_TRANSCRIPTION_MODAL_APP_NAME is required.",
            )
        if self.callable_type == "class" and (not self.class_name or not self.method_name):
            raise KnowledgeImportError(
                "modal_transcription_not_configured",
                "AI_YOUTUBE_TRANSCRIPTION_MODAL_CLASS_NAME and AI_YOUTUBE_TRANSCRIPTION_MODAL_METHOD_NAME are required.",
            )
        if self.callable_type == "function" and not self.function_name:
            raise KnowledgeImportError(
                "modal_transcription_not_configured",
                "AI_YOUTUBE_TRANSCRIPTION_MODAL_FUNCTION_NAME is required for function transcription.",
            )

        try:
            payload = self._remote_callable().remote(
                audio_bytes=audio_bytes or b"",
                filename=filename or "",
                content_type=content_type or "",
                youtube_url=youtube_url or "",
                max_audio_bytes=int(YOUTUBE_AUDIO_MAX_BYTES),
                source_url=source_url,
                metadata=source_metadata,
            )
        except KnowledgeImportError:
            raise
        except Exception as exc:
            message = str(exc)
            code = "modal_token_invalid" if "token validation failed" in message.lower() else "modal_transcription_failed"
            raise KnowledgeImportError(code, message) from exc

        text = payload.get("text") or payload.get("transcript") or payload.get("content")
        if not isinstance(text, str):
            raise KnowledgeImportError(
                "modal_transcription_invalid_response",
                "Modal transcription response must include a text, transcript, or content string.",
            )
        segments = payload.get("segments")
        return {
            "text": text,
            "language": payload.get("language"),
            "model": payload.get("model") or payload.get("transcription_model"),
            "segments_count": len(segments) if isinstance(segments, list) else payload.get("segments_count"),
        }

    def _remote_callable(self):
        handle = self._remote_handle
        if handle is None:
            try:
                import modal
            except ImportError as exc:
                raise KnowledgeImportError("modal_missing", "The modal Python package is required for transcription.") from exc
            lookup_kwargs = self._lookup_kwargs()
            if self.callable_type == "class":
                modal_class = modal.Cls.from_name(self.app_name, self.class_name, **lookup_kwargs)
                handle = getattr(modal_class(), self.method_name)
            elif self.callable_type == "function":
                handle = modal.Function.from_name(self.app_name, self.function_name, **lookup_kwargs)
            else:
                raise KnowledgeImportError(
                    "modal_transcription_not_configured",
                    f"Unsupported Modal transcription callable type: {self.callable_type!r}.",
                )
        if self.callable_type == "function" and self.timeout_seconds > 0 and hasattr(handle, "with_options"):
            handle = handle.with_options(timeout=self.timeout_seconds)
        return handle

    def _lookup_kwargs(self) -> dict[str, Any]:
        lookup_kwargs: dict[str, Any] = {}
        if self.environment_name:
            lookup_kwargs["environment_name"] = self.environment_name
        if self.version is not None:
            lookup_kwargs["version"] = self.version
        return lookup_kwargs


def _is_text_like(*, suffix: str, mime_type: str) -> bool:
    return suffix in TEXT_EXTENSIONS or mime_type in TEXT_MIME_TYPES or mime_type.startswith(TEXT_MIME_PREFIXES)


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _audio_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".ogg":
        return "audio/ogg"
    if suffix == ".webm":
        return "audio/webm"
    return "application/octet-stream"


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise KnowledgeImportError("pypdf_missing", "pypdf is required for PDF knowledge imports.") from exc

    reader = PdfReader(str(path))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as docx:
            document_xml = docx.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise KnowledgeImportError("invalid_docx", "Could not read DOCX document text.") from exc

    import xml.etree.ElementTree as ET

    root = ET.fromstring(document_xml)
    paragraphs: list[str] = []
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for paragraph in root.iter(f"{namespace}p"):
        parts = [node.text or "" for node in paragraph.iter(f"{namespace}t")]
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _clean_caption_text(text: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.upper() == "WEBVTT" or line.startswith(("Kind:", "Language:")):
            continue
        if _TIMESTAMP_RE.search(line) or line.isdigit():
            continue
        line = _WEBVTT_TAG_RE.sub("", line)
        line = html.unescape(line).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return " ".join(lines)


def _bounded_text(text: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", text or "").strip()
    if len(normalized) <= MAX_EXTRACTED_TEXT_CHARS:
        return normalized
    return normalized[:MAX_EXTRACTED_TEXT_CHARS].rstrip()
