# LLM Prompts & Structured Outputs

## Analyst schema
- The schema used by the Analyst is in `/config/prompts/analyst_schema.json`.
- All LLM outputs must validate. If they don't, retry with a short "fix to schema" prompt.
- Default Gemini model selection and system instructions live in `config/llm.yaml`.

## Analyst (first pass) — instruction
```
You are the Oddcrawler Analyst. Given page text, metadata, and detected signals,
write:
1) a 4–6 sentence neutral summary (no PII),
2) 2–6 bullets explaining *why* the page was flagged (concrete evidence),
3) a risk tag from {harmless-retro, fringe, conspiracy-leaning, coded-forum, unsafe, unknown},
4) a dangerous_content object (see schema) if applicable,
5) a confidence 0–1.
Return strict JSON per the schema. Do not include any additional keys.
```
