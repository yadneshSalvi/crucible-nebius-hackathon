from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

PROJECT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    root: Path
    provider: str
    model: str
    base_url: str
    api_key: str
    tavily_key: str
    allow_nebius: bool
    source_zip: Path | None

    @classmethod
    def read(cls) -> "Settings":
        # Read only the explicitly authorized services. Never load the whole file
        # into the worker environment, export it, or send it to an inference API.
        values = dotenv_values(PROJECT.parent / ".env")
        def setting(name: str, default: str = "") -> str:
            return os.environ.get(name, str(values.get(name) or default))
        provider = setting("CRUCIBLE_PROVIDER", "fireworks")
        routes = {
            "fireworks": ("accounts/fireworks/models/nemotron-3-ultra-nvfp4", "https://api.fireworks.ai/inference/v1", "FIREWORKS_AI_API_KEY"),
            "nebius": ("nvidia/Nemotron-3-Ultra-550b-a55b", "https://api.tokenfactory.nebius.com/v1", "NEBIUS_API_KEY"),
        }
        if provider not in routes:
            raise ValueError("CRUCIBLE_PROVIDER must be fireworks or nebius; no implicit fallback is available.")
        model, url, key = routes[provider]
        if provider == "nebius":
            model = setting("CRUCIBLE_NEBIUS_MODEL", model)
            if model not in {"nvidia/Nemotron-3-Ultra-550b-a55b", "nvidia/nemotron-3-super-120b-a12b"}:
                raise ValueError("Select an explicit supported Nebius model identity.")
        source_zip = PROJECT.parent / "artifacts/crucible-data-audit/occupancy.zip"
        return cls(
            root=Path(setting("CRUCIBLE_RUNTIME", str(PROJECT / "runtime"))).resolve(),
            provider=provider, model=model, base_url=url, api_key=setting(key),
            tavily_key=setting("TAVILY_API_KEY"),
            allow_nebius=setting("CRUCIBLE_ENABLE_NEBIUS", "false").lower() == "true",
            source_zip=source_zip if source_zip.is_file() else None,
        )

    def public(self) -> dict:
        return {
            "provider": self.provider, "model": self.model,
            "configured": bool(self.api_key),
            "qualified": self.provider == "fireworks",
            "reasoning_effort": "high", "max_output_tokens": 32000,
            "timeout_seconds": 480, "response_profile": "prompt_schema",
            "tavily_configured": bool(self.tavily_key),
            "nebius": {"model": "nvidia/Nemotron-3-Ultra-550b-a55b", "qualification": "pending", "development_calls": "disabled"},
            "fallback": "none", "data_release": "Authored claim text, public source excerpts, registered settings and released discovery aggregates only. No row-level labels.",
        }
