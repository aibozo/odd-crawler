#!/usr/bin/env python3
import json, time, hashlib
def demo_finding(url: str) -> dict:
    h = hashlib.sha1(url.encode()).hexdigest()[:8]
    return {
        "url": url,
        "summary": "Retro page with webring links and handmade HTML.",
        "why_flagged": ["webring widget", "table-based layout", "guestbook link"],
        "risk_tag": "harmless-retro",
        "dangerous_content": {"present": False, "category": "none", "notes": ""},
        "confidence": 0.75,
        "observation_ref": f"observation:{time.strftime('%Y-%m-%dT%H:%M:%SZ')}:{h}"
    }
if __name__ == "__main__":
    print(json.dumps(demo_finding("https://example.net/webring.html"), indent=2))
