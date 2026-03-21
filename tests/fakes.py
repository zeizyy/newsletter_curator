from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from types import SimpleNamespace


def encode_base64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def make_gmail_message(
    *,
    message_id: str,
    subject: str,
    from_header: str,
    date_header: str,
    html_body: str,
) -> dict:
    return {
        "id": message_id,
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_header},
                {"name": "Date", "value": date_header},
            ],
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": encode_base64url(html_body)},
                }
            ],
        },
    }


class _ExecuteWrapper:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeGmailService:
    def __init__(self, *, messages: list[dict], label_name: str = "Newsletters"):
        self._messages = {message["id"]: message for message in messages}
        self._ordered_ids = [message["id"] for message in messages]
        self.label_name = label_name
        self.sent_messages: list[dict] = []

    def users(self):
        return _FakeUsersResource(self)


class _FakeUsersResource:
    def __init__(self, service: FakeGmailService):
        self._service = service

    def labels(self):
        return _FakeLabelsResource(self._service)

    def messages(self):
        return _FakeMessagesResource(self._service)


class _FakeLabelsResource:
    def __init__(self, service: FakeGmailService):
        self._service = service

    def list(self, userId: str):
        return _ExecuteWrapper(
            {"labels": [{"id": "label-newsletters", "name": self._service.label_name}]}
        )


class _FakeMessagesResource:
    def __init__(self, service: FakeGmailService):
        self._service = service

    def list(self, userId: str, labelIds: list[str], q: str, pageToken: str | None = None):
        return _ExecuteWrapper({"messages": [{"id": msg_id} for msg_id in self._service._ordered_ids]})

    def get(self, userId: str, id: str, format: str):
        return _ExecuteWrapper(self._service._messages[id])

    def send(self, userId: str, body: dict):
        self._service.sent_messages.append(body)
        return _ExecuteWrapper({"id": f"sent-{len(self._service.sent_messages)}"})


class FakeSourceFetcher:
    def __init__(self, stories: list[dict]):
        self._stories = list(stories)
        self.calls = 0

    def __call__(self, config: dict) -> list[dict]:
        self.calls += 1
        return [dict(story) for story in self._stories]


class FakeArticleFetcher:
    def __init__(self, articles_by_url: dict[str, str]):
        self._articles_by_url = dict(articles_by_url)
        self.calls: list[str] = []

    def __call__(self, url: str, max_article_chars: int, timeout: int = 25, retries: int = 3) -> str:
        self.calls.append(url)
        return self._articles_by_url.get(url, "")[:max_article_chars]


@dataclass
class _FakeUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 5
    total_tokens: int = 15


class FakeOpenAI:
    def __init__(self):
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, *, model: str, messages: list[dict]):
        user_message = next(message["content"] for message in messages if message["role"] == "user")
        self.calls.append({"model": model, "messages": messages})

        if "Select the top stories." in user_message:
            response_text = self._build_ranking_response(user_message)
        elif "Write a concise summary of the article below." in user_message:
            response_text = self._build_summary_response(user_message)
        else:
            raise AssertionError(f"Unexpected OpenAI prompt: {user_message[:120]}")

        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response_text))],
            usage=_FakeUsage(),
        )

    def _build_ranking_response(self, prompt: str) -> str:
        max_items_match = re.search(r"up to (\d+) objects", prompt)
        max_items = int(max_items_match.group(1)) if max_items_match else 1
        item_count = len(re.findall(r"^\[\d+\]", prompt, flags=re.MULTILINE))
        categories = [
            "Markets / stocks / macro / economy",
            "Tech company news & strategy",
            "AI & ML industry developments",
            "Tech blogs",
            "Interesting datapoints & anomalies",
        ]
        payload = []
        for index in range(1, min(max_items, item_count) + 1):
            payload.append(
                {
                    "index": index,
                    "category": categories[(index - 1) % len(categories)],
                    "score": 9 - ((index - 1) % 3),
                    "rationale": f"Deterministic fake ranking for item {index}.",
                }
            )
        return json.dumps(payload)

    def _build_summary_response(self, prompt: str) -> str:
        article_text = prompt.split("Article text:\n", 1)[1].strip()
        headline_words = article_text.split()[:6]
        headline = " ".join(headline_words) or "Untitled"
        body = "\n".join(
            [
                "Key takeaways",
                f"- {headline} highlights the core development.",
                "- The fake summarizer keeps output deterministic for integration testing.",
                "Why this matters to me",
                "This matters because the smoke test proves the pipeline can run offline.",
            ]
        )
        return json.dumps({"headline": headline, "body": body})
