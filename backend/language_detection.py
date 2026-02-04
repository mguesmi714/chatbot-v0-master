"""
Language detection module.
Handles multilingual language detection with heuristic and LLM-based approaches.
"""
import re
import os
from dotenv import load_dotenv

# Load environment variables before using them
load_dotenv()

from openai import OpenAI

# Configuration
LANG_USE_LLM = os.getenv("LANG_USE_LLM", "false").strip().lower() in {"1", "true", "yes"}

# OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _is_language_token(s: str | None) -> bool:
    """Check if text is a language selection token."""
    if not s:
        return False
    tok = s.strip().lower()
    return tok in {
        "fr", "en", "ar",
        "french", "français", "francais",
        "english", "anglais",
        "arabic", "arabe", "عربي", "العربية"
    }


def normalize_lang(s: str | None) -> str | None:
    """Normalize language code to standard form (fr, en, ar)."""
    if not s:
        return None
    s = s.strip().lower()
    if s in {"fr", "en", "ar"}:
        return s
    if s in {"french", "français", "francais"}:
        return "fr"
    if s in {"english", "anglais"}:
        return "en"
    if s in {"arabic", "arabe", "عربي", "العربية"}:
        return "ar"
    return None


def _heuristic_lang(text: str) -> str:
    """Fast heuristic language detection without LLM."""
    t = (text or "").strip().lower()
    if not t:
        return "fr"
    
    # Strong Arabic indicators
    if re.search(r"[\u0600-\u06FF]", t):
        return "ar"

    # Quick unicode-based French detection (accents)
    if re.search(r"[éèêàâôûçùëïüœ]", t):
        return "fr"
    
    # French indicators
    # Expanded keyword lists
    fr_kw = [
        "bonjour", "merci", "s'il", "s'il vous", "svp", "que", "est", "le", "la", "les", "et", "pour", "avec",
        "renouvel", "location", "louer", "ordonnance", "mutuelle"
    ]
    # Expanded EN cues to catch short requests like "i want to buy"
    en_kw = [
        "hello", "hi", "hey", "thank", "thanks", "please", "how", "what",
        "i want", "i need", "i would like", "want", "need",
        "buy", "purchase", "order", "pay", "ship",
        "renew", "rental", "rent", "prescription", "insurance", "return"
    ]
    ar_kw = ["مرحبا", "شكرا", "من فضلك", "اريد", "أريد", "تجديد", "استئجار", "استرجاع", "إرجاع", "بطاقة", "وصفة"]

    fr_count = sum(1 for kw in fr_kw if kw in t)
    en_count = sum(1 for kw in en_kw if kw in t)
    ar_count = sum(1 for kw in ar_kw if kw in t or kw in text)

    # If Arabic words present, prefer Arabic
    if ar_count > 0:
        return "ar"

    # Heuristic: compare counts, prefer FR if accents or fr_count >= en_count
    if en_count > fr_count:
        return "en"
    return "fr"


def llm_detect_language(text: str) -> str:
    """Detect language among fr|en|ar. Fast heuristic first, optional LLM refinement."""
    if not text:
        return "fr"
    
    # Heuristic first (instant, robust)
    h = _heuristic_lang(text)
    if not LANG_USE_LLM:
        return h
    
    # Optional LLM refinement
    try:
        system = (
            "You are a language identifier.\n"
            "Reply with exactly one of: fr | en | ar. No punctuation, no explanation."
        )
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
        )
        content = (resp.choices[0].message.content or "").strip().lower()
        lang = normalize_lang(content)
        if lang in {"fr", "en", "ar"}:
            return lang
    except Exception:
        pass
    
    return h
