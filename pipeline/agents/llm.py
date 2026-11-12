"""Tüm ajanların ortak Claude istemcisi: JSON çıktı, görsel girdi, kayıt ve maliyet takibi."""
from __future__ import annotations

import base64
import json
import os
import re
import time

import anthropic

# $/1M token (girdi, çıktı). Maliyet raporu için yaklaşık değerler.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50), "claude-fable-5-2": (8.0, 40.0)}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "score": {"type": "integer"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "instructions": {"type": "string"},
    },
    "required": ["approved", "score", "issues", "instructions"],
    "additionalProperties": False,
}


class LLM:
    def __init__(self, log_path: str | None = None):
        self.client = anthropic.Anthropic(max_retries=4)
        self.worker_model = os.environ.get("AGENT_MODEL", "claude-opus-5-5")
        self.review_model = os.environ.get("REVIEW_MODEL", self.worker_model)
        self.log_path = log_path
        self.cost = 0.0
        self.calls = 0

    @staticmethod
    def image(path: str) -> dict:
        mt = "image/png" if path.endswith(".png") else "image/jpeg"
        with open(path, "rb") as f:
            return {"type": "image", "source": {"type": "base64", "media_type": mt, "data": base64.b64encode(f.read()).decode()}}

    def _log(self, rec: dict):
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def ask(self, agent: str, system: str, content, *, schema: dict | None = None, review=False, effort="medium") -> dict:
        """JSON döndürür. schema verilirse yapılandırılmış çıktı ile garanti edilir."""
        model = self.review_model if review else self.worker_model
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        output_config = {"effort": effort}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        messages = [{"role": "user", "content": content}]
        for attempt in range(3):
            t0 = time.time()
            resp = self.client.beta.messages.create(
                model=model, max_tokens=16000, system=system, messages=messages,
                output_config=output_config, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            self.calls += 1
            pin, pout = PRICES.get(model, (4.0, 20.0))
            u = resp.usage
            self.cost += (u.input_tokens * pin + u.output_tokens * pout) / 1e6
            if resp.stop_reason == "refusal":
                raise RuntimeError(f"{agent}: model isteği reddetti")
            text = "".join(b.text for b in resp.content if b.type == "text")
            try:
                data = json.loads(text) if schema else json.loads(re.search(r"\{.*\}", text, re.S).group(0))
                self._log({"agent": agent, "model": model, "secs": round(time.time() - t0, 1), "in": u.input_tokens, "out": u.output_tokens, "result": data})
                return data
            except Exception as e:
                messages = messages[:1] + [{"role": "assistant", "content": text or "(boş)"},
                                           {"role": "user", "content": f"Çıktın geçerli JSON değil ({e}). Sadece geçerli JSON nesnesi döndür."}]
        raise RuntimeError(f"{agent}: geçerli JSON alınamadı")
