from pathlib import Path

from modal_apps.youtube_transcription import (
    _detected_language,
    _run_whisper_pipeline,
    _speech_trim_bounds,
    _strip_trailing_hallucination_from_segments,
    _strip_trailing_transcription_hallucination,
)


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


def test_speech_trim_bounds_remove_trailing_non_speech_with_padding():
    start, end = _speech_trim_bounds(
        [{"start": 32_000, "end": 160_000}],
        total_samples=200_000,
        sampling_rate=16_000,
    )

    assert start == 28_000
    assert end == 176_000


def test_speech_trim_bounds_keep_full_audio_when_vad_finds_no_speech():
    assert _speech_trim_bounds([], total_samples=200_000, sampling_rate=16_000) == (0, 200_000)


def test_known_trailing_subtitle_credit_hallucination_is_removed():
    text = "До новых встреч. Редактор субтитров А.Семкин Корректор А.Егорова"
    segments = [
        {"start": 1.0, "end": 2.0, "text": "До новых встреч."},
        {
            "start": 2.0,
            "end": 3.0,
            "text": "Редактор субтитров А.Семкин Корректор А.Егорова",
        },
    ]

    assert _strip_trailing_transcription_hallucination(text) == "До новых встреч."
    assert _strip_trailing_hallucination_from_segments(segments) == [segments[0]]


def test_subtitle_credit_words_are_preserved_when_they_are_not_at_the_end():
    text = (
        "Редактор субтитров А.Семкин Корректор А.Егорова — "
        "выдуманная строка, затем речь продолжается."
    )

    assert _strip_trailing_transcription_hallucination(text) == text
