"""Gemini client wrappers for Oddcrawler."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from dotenv import load_dotenv

try:  # pragma: no cover - optional dependency guard
    from google import genai
    from google.genai import types
except ImportError as exc:  # pragma: no cover
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
    _IMPORT_ERROR: Optional[ImportError] = exc
else:  # pragma: no cover
    _IMPORT_ERROR = None

load_dotenv()


class GeminiConfigurationError(RuntimeError):
    """Raised when Gemini configuration or dependencies are missing."""


class GeminiClient:
    """Small helper around the Gemini SDK with config-driven model selection."""

    def __init__(
        self,
        *,
        model_key: str = "analyst",
        api_key: Optional[str] = None,
        config_path: Path | str = "config/llm.yaml",
    ) -> None:
        if _IMPORT_ERROR is not None:
            raise GeminiConfigurationError(
                "google-genai is required for Gemini integrations. Install it with 'pip install google-genai'."
            ) from _IMPORT_ERROR

        self.config = self._load_config(config_path, model_key)
        self.model = self.config["model"]
        if self.model not in {"gemini-2.5-pro", "gemini-2.5-flash"}:
            raise GeminiConfigurationError(f"Unsupported Gemini model configured: {self.model}")
        self.system_instruction = self.config.get("system_instruction", "")
        self.model_key = model_key

        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise GeminiConfigurationError("GEMINI_API_KEY is not set. Add it to your .env file (see .env.example).")

        self.client = genai.Client(api_key=api_key)

    @staticmethod
    def _load_config(path: Path | str, model_key: str) -> Dict[str, Any]:
        import yaml

        config_path = Path(path)
        if not config_path.exists():
            raise GeminiConfigurationError(f"LLM config not found at {config_path}")
        with config_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        model_cfg = payload.get(model_key)
        if not isinstance(model_cfg, dict):
            raise GeminiConfigurationError(f"Missing LLM config for key '{model_key}'")
        return model_cfg

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: Optional[str] = None,
    ) -> str:
        """Generate plain text with optional system instruction override."""

        contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
        instructions = [types.Part.from_text(text=system_instruction or self.system_instruction)]

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=instructions),
        )
        return self._collect_text(response)

    # ------------------------------------------------------------------
    # Analyst-specific helper (JSON output)
    # ------------------------------------------------------------------
    def generate_analyst_finding(
        self,
        observation: Mapping[str, Any],
        *,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self.model_key != "analyst":
            raise GeminiConfigurationError("Analyst findings require the 'analyst' model configuration")

        prompt = self._build_analyst_prompt(observation, extra_context)
        text = self.generate_text(prompt)
        return self._parse_json(text)

    # ------------------------------------------------------------------
    # Prompt builders / parsing helpers
    # ------------------------------------------------------------------
    def _build_analyst_prompt(
        self,
        observation: Mapping[str, Any],
        extra_context: Optional[Dict[str, Any]],
    ) -> str:
        extract = observation.get("extract") if isinstance(observation, Mapping) else None
        excerpt = ""
        if isinstance(extract, Mapping):
            excerpt = str(extract.get("text_excerpt") or "")[:2000]
        features = observation.get("features") if isinstance(observation, Mapping) else {}
        feature_summary = json.dumps(features, ensure_ascii=False, indent=2)

        prompt_lines = [
            "Analyze the following Oddcrawler observation and return JSON per the schema.",
            f"URL: {observation.get('url', 'unknown')}",
            f"Fetched at: {observation.get('fetched_at', 'unknown')}",
            "Text excerpt:",
            excerpt if excerpt else "[no excerpt]",
            "",
            "Features JSON:",
            feature_summary,
        ]
        if extra_context:
            prompt_lines.append("")
            prompt_lines.append("Additional context:")
            prompt_lines.append(json.dumps(extra_context, ensure_ascii=False, indent=2))
        prompt_lines.append("")
        prompt_lines.append(
            "Return ONLY valid JSON matching config/prompts/analyst_schema.json with keys: "
            "url, summary, why_flagged, risk_tag, dangerous_content, confidence, observation_ref."
        )
        return "\n".join(prompt_lines)

    @staticmethod
    def _collect_text(response: types.GenerateContentResponse) -> str:
        chunks: list[str] = []
        for candidate in response.candidates or []:
            if candidate.content:
                for part in candidate.content.parts:
                    if part.text:
                        chunks.append(part.text)
        return "\n".join(chunks).strip()

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                snippet = text[start : end + 1]
                return json.loads(snippet)
            raise


__all__ = ["GeminiClient", "GeminiConfigurationError"]
