from __future__ import annotations

from curator.content import fetch_article_details


class _FakeResponse:
    def __init__(self, html: str):
        self._payload = html.encode("utf-8")
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size: int = 65536):
        for start in range(0, len(self._payload), chunk_size):
            yield self._payload[start : start + chunk_size]

    def close(self):
        return None


class _FakeSession:
    def __init__(self, html: str):
        self._html = html
        self.closed = False

    def get(self, url: str, headers: dict, timeout: int, stream: bool = False):
        assert stream is True
        return _FakeResponse(self._html)

    def close(self):
        self.closed = True


class _SlowResponse:
    def __init__(self, chunks: list[bytes], advance_time):
        self._chunks = chunks
        self._advance_time = advance_time
        self.encoding = "utf-8"
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size: int = 65536):
        for chunk in self._chunks:
            self._advance_time()
            yield chunk

    def close(self):
        self.closed = True


class _SlowSession:
    def __init__(self, response: _SlowResponse):
        self._response = response
        self.closed = False

    def get(self, url: str, headers: dict, timeout: int, stream: bool = False):
        assert stream is True
        return self._response

    def close(self):
        self.closed = True


def test_fetch_article_details_caps_response_bytes(monkeypatch):
    early_article = "Critical context appears early in the article body. " * 4
    late_tail = "LATE_TAIL_SHOULD_NOT_BE_PRESENT " * 20
    html = (
        "<html><head><title>Large page</title></head><body><article>"
        f"{early_article}</article>"
        f"<div>{late_tail}</div>"
        "</body></html>"
    )

    monkeypatch.setattr("curator.content.MAX_FETCH_RESPONSE_BYTES", 180)
    monkeypatch.setattr("curator.content.requests.Session", lambda: _FakeSession(html))

    details = fetch_article_details("https://example.com/large", max_article_chars=1000)

    assert details["document_title"] == "Large page"
    assert "Critical context appears early" in details["article_text"]
    assert "LATE_TAIL_SHOULD_NOT_BE_PRESENT" not in details["article_text"]


def test_fetch_article_details_times_out_total_response_read(monkeypatch):
    current_time = 0.0

    def fake_monotonic() -> float:
        return current_time

    def advance_time() -> None:
        nonlocal current_time
        current_time += 2.0

    response = _SlowResponse(
        [
            b"<html><head><title>Slow page</title></head><body><article>",
            b"still loading",
            b"</article></body></html>",
        ],
        advance_time,
    )
    session = _SlowSession(response)

    monkeypatch.setattr("curator.content.requests.Session", lambda: session)
    monkeypatch.setattr("curator.content.time.monotonic", fake_monotonic)

    details = fetch_article_details("https://example.com/slow", max_article_chars=1000, timeout=3)

    assert details == {
        "article_text": "",
        "document_title": "",
        "document_excerpt": "",
    }
    assert response.closed is True
    assert session.closed is True
