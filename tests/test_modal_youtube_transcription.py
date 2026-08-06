from pathlib import Path

from modal_apps.youtube_transcription import _detected_language, _run_whisper_pipeline


def test_whisper_pipeline_uses_native_long_form_generation():
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_pipeline(audio_path: str, **kwargs):
        calls.append((audio_path, kwargs))
        return {"text": "hello", "chunks": []}

    result = _run_whisper_pipeline(
        pipeline=fake_pipeline,
        audio_path=Path("audio.wav"),
        generate_kwargs={"task": "transcribe"},
    )

    assert result["text"] == "hello"
    assert calls == [
        (
            "audio.wav",
            {
                "return_timestamps": True,
                "return_language": True,
                "generate_kwargs": {"task": "transcribe"},
            },
        )
    ]
    assert "chunk_length_s" not in calls[0][1]
    assert "batch_size" not in calls[0][1]


def test_detected_language_uses_dominant_whisper_chunk_language():
    result = {
        "chunks": [
            {"text": "one", "language": "russian"},
            {"text": "two", "language": "Russian"},
            {"text": "three", "language": "english"},
        ]
    }

    assert _detected_language(result, selected_language=None) == "russian"


def test_configured_language_takes_precedence_over_detection():
    result = {"chunks": [{"text": "hello", "language": "english"}]}

    assert _detected_language(result, selected_language="ru") == "ru"
