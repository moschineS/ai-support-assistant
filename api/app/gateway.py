"""Provider gateway: one interface, two substrates.

- ``OllamaGateway`` — fully local/offline path (demo default).
- ``OpenAIGateway`` — cloud path (Azure OpenAI in the target architecture,
  api.openai.com locally; the wire format is identical).

Deliberately raw httpx, no SDK and no framework: both wire formats are
small, and owning them keeps the dependency surface minimal and every
request explainable (ADR-004). Embedding vectors are returned as plain
``list[float]``; chat is exposed streaming-first because the UI streams
drafts over SSE.

Token usage for a streamed chat is captured on the instance in
``last_usage`` after the stream is fully consumed (both providers send
usage only in their final frame).
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


class OllamaGateway:
    provider = "ollama"

    def __init__(self, s: Settings):
        self.base = s.ollama_base_url.rstrip("/")
        self.chat_model = s.ollama_chat_model
        self.embed_model = s.ollama_embed_model
        self.last_usage: tuple[int | None, int | None] = (None, None)

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Batch endpoint (Ollama >= 0.2.6); fall back to the older
        # one-prompt-per-call endpoint on 404 so any installed version works.
        try:
            r = httpx.post(
                f"{self.base}/api/embed",
                json={"model": self.embed_model, "input": texts},
                timeout=httpx.Timeout(EMBED_TIMEOUT, connect=CONNECT_TIMEOUT),
            )
            if r.status_code != 404:
                r.raise_for_status()
                return r.json()["embeddings"]
        except httpx.ConnectError as e:
            raise GatewayError(f"Ollama not reachable at {self.base}: {e}") from e

        out: list[list[float]] = []
        for t in texts:
            r = httpx.post(
                f"{self.base}/api/embeddings",
                json={"model": self.embed_model, "prompt": t},
                timeout=httpx.Timeout(EMBED_TIMEOUT, connect=CONNECT_TIMEOUT),
            )
            r.raise_for_status()
            out.append(r.json()["embedding"])
        return out

    def chat_stream(self, system: str, user: str) -> Iterator[str]:
        self.last_usage = (None, None)
        try:
            with httpx.stream(
                "POST",
                f"{self.base}/api/chat",
                json={
                    "model": self.chat_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": True,
                },
                timeout=httpx.Timeout(CHAT_TIMEOUT, connect=CONNECT_TIMEOUT),
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    obj = json.loads(line)
                    piece = obj.get("message", {}).get("content")
                    if piece:
                        yield piece
                    if obj.get("done"):
                        self.last_usage = (
                            obj.get("prompt_eval_count"),
                            obj.get("eval_count"),
                        )
        except httpx.ConnectError as e:
            raise GatewayError(f"Ollama not reachable at {self.base}: {e}") from e


class OpenAIGateway:
    provider = "openai"

    def __init__(self, s: Settings):
        if not s.openai_api_key:
            raise GatewayError("PROVIDER=openai but OPENAI_API_KEY is not set")
        self.headers = {"Authorization": f"Bearer {s.openai_api_key}"}
        self.chat_model = s.openai_chat_model
        self.embed_model = s.openai_embed_model
        self.last_usage: tuple[int | None, int | None] = (None, None)

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers=self.headers,
            json={"model": self.embed_model, "input": texts},
            timeout=httpx.Timeout(EMBED_TIMEOUT, connect=CONNECT_TIMEOUT),
        )
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def chat_stream(self, system: str, user: str) -> Iterator[str]:
        self.last_usage = (None, None)
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


Gateway = OllamaGateway | OpenAIGateway


def get_gateway(s: Settings | None = None) -> Gateway:
    s = s or get_settings()
    if s.provider == "ollama":
        return OllamaGateway(s)
    if s.provider == "openai":
        return OpenAIGateway(s)
    raise GatewayError(f"Unknown PROVIDER '{s.provider}' (use 'ollama' or 'openai')")