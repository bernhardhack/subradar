"""Thin wrapper around Claude with structured output and an on-disk cache."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"


class Claude:
    def __init__(self, cache_dir: Path, model: str | None = None, client=None):
        self.model = model or os.environ.get("SUBRADAR_MODEL", DEFAULT_MODEL)
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def structured(self, *, system: str, prompt: str, tool_name: str, schema: dict, max_tokens: int = 8000) -> dict:
        """Ask Claude for output matching `schema`; cached by full input."""
        key = hashlib.sha256(json.dumps([self.model, system, prompt, schema], sort_keys=True).encode()).hexdigest()
        cache_file = self.cache_dir / f"{key[:24]}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text())
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            tools=[{"name": tool_name, "description": "Return the result.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": prompt}],
        )
        block = next((b for b in msg.content if getattr(b, "type", "") == "tool_use"), None)
        if block is None:
            raise RuntimeError("Claude returned no structured output")
        result = dict(block.input)
        cache_file.write_text(json.dumps(result, ensure_ascii=False))
        return result
