"""Byte-exact range and rejection behavior for every protected media route."""
import pytest
from starlette.requests import Request

from services.api.focus_api.routes import _file_response, _parse_range

from .test_uploads import assert_error


VALID_RANGES = [
    ("bytes=0-3", 0, 3),
    ("bytes=2-", 2, None),
    ("bytes=-4", -4, None),
    ("bytes=-1", -1, None),
    ("bytes={last}-", -1, None),
    ("bytes=0-0", 0, 0),
    ("bytes=0-{size}", 0, None),
    ("bytes=2-{beyond}", 2, None),
    ("bytes=-{beyond}", 0, None),
]

INVALID_RANGES = [
    "",
    "bytes=",
    "bytes=-",
    "bytes=-0",
    "bytes=-1-3",       # Negative start, not a suffix.
    "bytes=0--1",       # Negative end.
    "bytes=--4",
    "bytes=4-2",
    "bytes={size}-",
    "bytes={size}-{beyond}",
    "bytes={beyond}-",
    "bytes=abc-def",
    "bytes=0",
    "bytes=0-1-2",
    "bytes=0-1,2-3",
    "bytes=0-1,",
    "items=0-3",
    "bytes=+1-3",
    "bytes=0-+3",
    "bytes=-+4",
    "bytes=1_0-20",
    "bytes=0-1_0",
    "bytes=0 -3",
    "bytes=0- 3",
    "bytes=0-" + "9" * 5000,  # Must not escape as an integer-conversion error.
]


def range_header(template, size):
    return template.format(size=size, last=size - 1, beyond=size + 10)


@pytest.mark.parametrize("template,start,end", VALID_RANGES)
def test_parse_valid_ranges(template, start, end):
    size = 32
    start = start if start >= 0 else size + start
    end = size - 1 if end is None else end
    assert _parse_range(range_header(template, size), size) == (start, end)


@pytest.mark.parametrize("template", INVALID_RANGES, ids=lambda value: value[:60])
def test_parse_invalid_ranges(template):
    with pytest.raises(ValueError):
        _parse_range(range_header(template, 32), 32)


def test_parse_rejects_non_ascii_digits():
    with pytest.raises(ValueError):
        _parse_range("bytes=١-٣", 32)


@pytest.mark.parametrize("size", [0, -1])
@pytest.mark.parametrize("header", ["bytes=0-", "bytes=-4", "bytes=0-0"])
def test_parse_rejects_ranges_without_file_bytes(size, header):
    with pytest.raises(ValueError):
        _parse_range(header, size)


def test_full_media_responses_have_exact_lengths(ready_media):
    api, data, _, _, media = ready_media
    for path, payload, mime in media:
        response = api.client.get(path, headers=api.auth(data["token"]))
        assert response.status_code == 200
        assert response.content == payload
        assert response.headers["content-length"] == str(len(payload))
        assert "content-range" not in response.headers
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["content-type"] == mime


@pytest.mark.parametrize("template,start,end", VALID_RANGES)
def test_partial_media_responses_are_byte_exact(ready_media, template, start, end):
    api, data, _, _, media = ready_media
    for path, payload, mime in media:
        size = len(payload)
        first = start if start >= 0 else size + start
        last = size - 1 if end is None else end
        response = api.client.get(path, headers={
            **api.auth(data["token"]), "Range": range_header(template, size),
        })
        assert response.status_code == 206
        assert response.content == payload[first:last + 1]
        assert response.headers["content-length"] == str(last - first + 1)
        assert response.headers["content-range"] == f"bytes {first}-{last}/{size}"
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["content-type"] == mime


@pytest.mark.parametrize("template", INVALID_RANGES, ids=lambda value: value[:60])
def test_invalid_media_ranges_return_empty_416(ready_media, template):
    api, data, _, _, media = ready_media
    for path, payload, _ in media:
        response = api.client.get(path, headers={
            **api.auth(data["token"]), "Range": range_header(template, len(payload)),
        })
        assert response.status_code == 416
        assert response.content == b""
        assert response.headers["content-length"] == "0"
        assert response.headers["content-range"] == f"bytes */{len(payload)}"
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["cache-control"] == "private, no-store"


def test_duplicate_range_headers_cannot_silently_select_one_range(ready_media):
    api, data, _, _, media = ready_media
    for path, payload, _ in media:
        response = api.client.get(path, headers=[
            *api.auth(data["token"]).items(),
            ("Range", "bytes=0-1"),
            ("Range", "bytes=2-3"),
        ])
        assert response.status_code == 416
        assert response.content == b""
        assert response.headers["content-length"] == "0"
        assert response.headers["content-range"] == f"bytes */{len(payload)}"
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("header", ["bytes=-4", "bytes=2-", "bytes=999999999-", "bytes=bad", ""])
def test_range_validation_never_precedes_media_authorization(ready_media, header):
    api, data, _, stranger, media = ready_media
    for path, _, _ in media:
        for token, status, code in [
            (None, 401, "UNAUTHORIZED"),
            ("unknown", 401, "UNAUTHORIZED"),
            (stranger, 404, "NOT_FOUND"),
        ]:
            response = api.client.get(path, headers={**api.auth(token), "Range": header})
            assert_error(response, status, code)
            assert "content-range" not in response.headers
            assert "accept-ranges" not in response.headers


@pytest.mark.parametrize("header", [None, "bytes=0-", "bytes=-1", "bytes=0-0"])
def test_empty_file_responses(tmp_path, header):
    path = tmp_path / "empty.wav"
    path.write_bytes(b"")
    headers = [] if header is None else [(b"range", header.encode("ascii"))]
    request = Request({"type": "http", "headers": headers})
    response = _file_response(request, path, "audio/wav")
    assert response.status_code == (200 if header is None else 416)
    assert response.body == b""
    assert response.headers["content-length"] == "0"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "private, no-store"
    if header is None:
        assert "content-range" not in response.headers
    else:
        assert response.headers["content-range"] == "bytes */0"
