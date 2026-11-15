"""Small wrapper over the Anthropic SDK: model, effort, refusal fallback, JSON output and usage accounting."""

from __future__ import annotations

import json
import os

MODEL = os.environ.get("BHAVSETU_MODEL", "claude-opus-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    pass


class Claude:
    def __init__(self, client=None, model: str = MODEL):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def _create(self, messages: list, effort: str, fmt: dict | None = None, system: str | None = None):
        output_config: dict = {"effort": effort}
        if fmt:
            output_config["format"] = fmt
        kwargs = dict(model=self.model, max_tokens=16000, messages=messages, output_config=output_config,
                      betas=[FALLBACK_BETA], fallbacks="default")
        if system:
            kwargs["system"] = system
        response = self.client.beta.messages.create(**kwargs)
        self.calls += 1
        usage = getattr(response, "usage", None)
        if usage:
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        if response.stop_reason == "refusal":
            raise LLMError("the model declined this request")
        if response.stop_reason == "max_tokens":
            raise LLMError("the response was cut off")
        return response

    def text(self, messages: list, effort: str = "medium", system: str | None = None) -> str:
        response = self._create(messages, effort, None, system)
        return "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()

    def json(self, messages: list, schema: dict, effort: str = "medium", system: str | None = None) -> dict:
        text = self.text_json(messages, schema, effort, system)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("invalid JSON from the model") from exc

    def text_json(self, messages, schema, effort, system):
        response = self._create(messages, effort, {"type": "json_schema", "schema": schema}, system)
        return next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
