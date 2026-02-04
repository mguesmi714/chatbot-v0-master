from __future__ import annotations

import os
from pathlib import Path


def load_system_prompt() -> str:
    """
    Load the system prompt from backend/prompts/system.md
    """
    prompt_path = Path(__file__).resolve().parent / "prompts" / "system.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    return prompt_path.read_text(encoding="utf-8").strip()


def should_reload_prompt() -> bool:
    """
    If PROMPT_RELOAD=true, reload prompt at each request (handy in dev).
    """
    return os.getenv("PROMPT_RELOAD", "false").strip().lower() in {"1", "true", "yes", "y"}
