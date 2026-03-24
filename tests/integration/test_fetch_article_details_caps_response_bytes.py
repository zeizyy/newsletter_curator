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

    def get(self, url: str, headers: dict, timeout: int, stream: bool = False):
        assert stream is True
        return _FakeResponse(self._html)


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
