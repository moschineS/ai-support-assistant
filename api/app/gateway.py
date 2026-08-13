"""OpenAI-compatible model gateway (api.openai.com locally, Azure OpenAI
in the cloud target — the wire format is identical).

Deliberately raw httpx, no SDK and no framework: the wire format is
small, and owning it keeps the dependency surface minimal and every
request explainable (ADR-004). The interface is exactly the two
capabilities the system needs — ``embed`` and ``chat_stream`` — so a
different substrate (e.g. an in-environment model server for strict
no-egress policies) could implement it without touching any caller.

Every transport or HTTP failure is wrapped in ``GatewayError`` so the
assist pipeline can convert it into a typed, audited refusal instead of
leaking a raw exception (ADR-005).

Token usage for a streamed chat is captured on the instance in
``last_usage`` after the stream is fully consumed (usage arrives only in
the final frame).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

from .config import Settings, get_settings

CONNECT_TIMEOUT = 10.0
EMBED_TIMEOUT = 180.0
CHAT_TIMEOUT = 300.0


class GatewayError(RuntimeError):
    pass


class OpenAIGateway:
    def __init__(self, s: Settings):
        if not s.openai_api_key:
            raise GatewayError("OPENAI_API_KEY is not set")
        self.headers = {"Authorization": f"Bearer {s.openai_api_key}"}
        self.chat_model = s.openai_chat_model
        self.embed_model = s.openai_embed_model
        self.last_usage: tuple[int | None, int | None] = (None, None)

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            r = httpx.post(
                "https://api.openai.com/v1/embeddings",
                headers=self.headers,
                json={"model": self.embed_model, "input": texts},
                timeout=httpx.Timeout(EMBED_TIMEOUT, connect=CONNECT_TIMEOUT),
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise GatewayError(f"embedding request failed: {e}") from e
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def chat_stream(self, system: str, user: str) -> Iterator[str]:
        self.last_usage = (None, None)
        try:
            with httpx.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers=self.headers,
                json={
                    "model": self.chat_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                },
                timeout=httpx.Timeout(CHAT_TIMEOUT, connect=CONNECT_TIMEOUT),
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: "):]
                    if payload == "[DONE]":
                        break
                    obj = json.loads(payload)
                    if usage := obj.get("usage"):
                        self.last_usage = (
                            usage.get("prompt_tokens"),
                            usage.get("completion_tokens"),
                        )
                    choices = obj.get("choices")
                    if choices:
                        piece = choices[0].get("delta", {}).get("content")
                        if piece:
                            yield piece
        except httpx.HTTPError as e:
            raise GatewayError(f"chat request failed: {e}") from e


Gateway = OpenAIGateway


def get_gateway(s: Settings | None = None) -> Gateway:
    return OpenAIGateway(s or get_settings())