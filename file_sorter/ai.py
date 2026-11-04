"""Optional: ask Claude what a file is, for files the built-in knowledge can't explain.

Only the file's path, name, size, dates, detected type and embedded program info are
sent. File contents are never uploaded.

Needs `pip install anthropic` and an API key in the ANTHROPIC_API_KEY environment
variable (or an `ant auth login` profile).
"""

from __future__ import annotations

import os

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = (
    "You help a non-technical person clean up their computer's storage. You are shown "
    "metadata about one file on their disk (never its contents). Explain, in plain language "
    "and under 200 words:\n"
    "1. What this file most likely is and which program or part of the system uses it.\n"
    "2. What would happen if they deleted it, and whether they can safely move it to another drive.\n"
    "3. A clear recommendation: delete, move to another drive, keep, or don't touch.\n"
    "If you aren't sure, say so and explain how they could find out. Never guess "
    "confidently about system files; err on the side of caution."
)


def is_available() -> tuple[bool, str]:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "The 'anthropic' package isn't installed. Run: pip install anthropic"
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.path.isdir(os.path.expanduser("~/.config/anthropic"))):
        return False, ("No Claude API key found. Set the ANTHROPIC_API_KEY environment variable "
                       "(get a key at https://console.anthropic.com) and restart the app.")
    return True, ""


def ask_about_file(facts: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Here is the file:\n\n{facts}"}],
        )
    except anthropic.AuthenticationError:
        return "Claude rejected the API key. Check ANTHROPIC_API_KEY."
    except anthropic.RateLimitError:
        return "Claude is rate-limiting requests right now. Try again in a minute."
    except anthropic.APIStatusError as e:
        return f"Claude returned an error ({e.status_code}): {e.message}"
    except anthropic.APIConnectionError:
        return "Couldn't reach Claude. Check your internet connection."

    if response.stop_reason == "refusal":
        return "Claude declined to answer this one."
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or "Claude didn't return an answer."
