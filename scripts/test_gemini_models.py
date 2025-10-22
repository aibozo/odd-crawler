#!/usr/bin/env python3
"""Quick smoke test for Gemini 2.5 Pro and Flash models."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types


def build_prompt(question: str) -> list[types.Content]:
    return [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)],
        )
    ]


def streamline_response(response: types.GenerateContentResponse) -> str:
    chunks: list[str] = []
    for candidate in response.candidates or []:
        if candidate.content:
            for part in candidate.content.parts:
                if part.text:
                    chunks.append(part.text)
    return "\n".join(chunks).strip()


def run(model: str, question: str) -> str:
    contents = build_prompt(question)
    config = types.GenerateContentConfig(
        system_instruction=[
            types.Part.from_text(text="Respond clearly. Show reasoning before the final answer."),
        ],
    )
    response = client.models.generate_content(model=model, contents=contents, config=config)
    return streamline_response(response)


if __name__ == "__main__":
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set. Add it to .env before running this test.")

    client = genai.Client(api_key=api_key)
    question = "What is 37 * 29? Explain your reasoning briefly, then give the final answer."

    for model in ("gemini-2.5-pro", "gemini-2.5-flash"):
        print(f"--- Testing {model} ---")
        try:
            answer = run(model, question)
            print(answer)
        except Exception as exc:  # pragma: no cover - interactive check
            print(f"Error calling {model}: {exc}")
        print()
