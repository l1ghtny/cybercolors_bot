import asyncio

import pytest

from src.commands.misc import cats


CORRUPT_CATAAS_RESPONSE = (
    b'{"message":"Input buffer has corrupt header: glib: XML parse error: '
    b'Error domain 1 code 68 on line 8 column 2 of data: StartTag: invalid element name"}'
)
JPEG_RESPONSE = b"\xff\xd8\xff\xe0fake-jpeg"
PNG_RESPONSE = b"\x89PNG\r\n\x1a\nfake-png"


class FakeResponse:
    def __init__(self, data: bytes, *, status: int = 200, content_type: str = "image/jpeg"):
        self.data = data
        self.status = status
        self.headers = {"Content-Type": content_type}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def read(self) -> bytes:
        return self.data


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get(self, url, *, params=None):
        self.requests.append((url, params))
        return self.responses.pop(0)


class FakeInteractionResponse:
    def __init__(self):
        self.deferred = False

    async def defer(self):
        self.deferred = True


class FakeInteraction:
    def __init__(self):
        self.response = FakeInteractionResponse()
        self.edits = []

    async def edit_original_response(self, **kwargs):
        self.edits.append(kwargs)


def install_fake_session(monkeypatch, responses):
    session = FakeSession(responses)
    session_options = {}

    def fake_client_session(**kwargs):
        session_options.update(kwargs)
        return session

    monkeypatch.setattr(cats.aiohttp, "ClientSession", fake_client_session)
    return session, session_options


def test_fetch_cat_retries_corrupt_json_and_preserves_real_image_type(monkeypatch):
    session, session_options = install_fake_session(
        monkeypatch,
        [
            FakeResponse(CORRUPT_CATAAS_RESPONSE, content_type="application/json"),
            FakeResponse(JPEG_RESPONSE),
        ],
    )

    image = asyncio.run(cats._fetch_cat_image())

    assert image.filename == "cat.jpg"
    assert image.fp.read() == JPEG_RESPONSE
    assert session.requests == [
        ("https://cataas.com/cat", None),
        ("https://cataas.com/cat", None),
    ]
    assert session_options["headers"] == {"Accept": "image/*"}


def test_fetch_cat_with_text_url_encodes_path_and_uses_query_params(monkeypatch):
    session, _session_options = install_fake_session(
        monkeypatch,
        [FakeResponse(PNG_RESPONSE, content_type="image/png")],
    )

    image = asyncio.run(cats._fetch_cat_image("кот / cat?"))

    assert image.filename == "cat.png"
    assert session.requests == [
        (
            "https://cataas.com/cat/says/%D0%BA%D0%BE%D1%82%20%2F%20cat%3F",
            {"fontColor": "#FFFFFF"},
        )
    ]


def test_fetch_cat_rejects_non_images_after_bounded_retries(monkeypatch):
    session, _session_options = install_fake_session(
        monkeypatch,
        [
            FakeResponse(CORRUPT_CATAAS_RESPONSE, status=500, content_type="application/json")
            for _ in range(cats.CAT_FETCH_ATTEMPTS)
        ],
    )

    with pytest.raises(cats.CatImageUnavailable):
        asyncio.run(cats._fetch_cat_image())

    assert len(session.requests) == cats.CAT_FETCH_ATTEMPTS


def test_cat_command_defers_and_returns_safe_error(monkeypatch):
    async def unavailable(_text=None):
        raise cats.CatImageUnavailable

    monkeypatch.setattr(cats, "_fetch_cat_image", unavailable)
    interaction = FakeInteraction()

    asyncio.run(cats.cat_command(interaction))

    assert interaction.response.deferred is True
    assert interaction.edits == [{"content": cats.CAT_UNAVAILABLE_MESSAGE}]
