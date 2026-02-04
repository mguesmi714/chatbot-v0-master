"""
RAG (Retrieval-Augmented Generation) module.
Handles CSV-based Q&A retrieval with lexical and embedding-based search.
"""
import re
import unicodedata
import csv
from pathlib import Path
from typing import Optional
import os
from dotenv import load_dotenv

# Load environment variables before using them
load_dotenv()

from openai import OpenAI

# Global state
RAG_INDEX: list[dict] = []
LOADED_RAG_PATH: Optional[str] = None

# Configuration from environment
RAG_CSV_PATH = os.getenv("RAG_CSV_PATH", "QR.csv").strip()
RAG_USE_EMBED = os.getenv("RAG_USE_EMBED", "false").strip().lower() in {"1", "true", "yes"}
RAG_TRANSLATE = os.getenv("RAG_TRANSLATE", "false").strip().lower() in {"1", "true", "yes"}
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# --------- Vector utilities ---------
def _vec_norm(v: list[float]) -> float:
    """Calculate vector norm (L2 distance)."""
    if not v:
        return 1.0
    return (sum(x * x for x in v) ** 0.5) or 1.0


def _cosine(a: list[float], b: list[float], b_norm: float | None = None) -> float:
    """Calculate cosine similarity between two vectors."""
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    an = _vec_norm(a)
    bn = b_norm if b_norm is not None else _vec_norm(b)
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (an * bn) if an and bn else 0.0


def _embed(text: str) -> list[float]:
    """Generate embedding for text using OpenAI."""
    text = (text or "").replace("\n", " ").strip()
    if not text:
        return []
    resp = client.embeddings.create(model=EMBED_MODEL, input=text)
    return resp.data[0].embedding


# --------- Text processing utilities ---------
def _strip_accents(s: str) -> str:
    """Remove accents from text for normalization."""
    return ''.join(c for c in unicodedata.normalize('NFD', s or '') if unicodedata.category(c) != 'Mn').lower()


def _fix_spacing(s: str) -> str:
    """Fix common spacing issues like 'nefonctionne' -> 'ne fonctionne'."""
    s = (s or "").lower()
    # Fix common patterns where words run together
    patterns = [
        (r'\bne([a-z])', r'ne \1'),  # 'nefonctionne' -> 'ne fonctionne'
        (r'\bce([a-z])', r'ce \1'),  # 'ceest' -> 'ce est'
        (r'\bqu([a-z])', r'qu \1'),  # 'quest' -> 'qu est'
    ]
    for pattern, replacement in patterns:
        s = re.sub(pattern, replacement, s)
    return s


def _tokenize_norm(s: str) -> set[str]:
    """Tokenize and normalize text with synonym expansion."""
    t = _fix_spacing(s)  # Fix spacing issues first
    t = _strip_accents(t)
    raw = [x for x in re.split(r"[^a-z0-9]+", t) if x]
    out: set[str] = set()
    for tok in raw:
        out.add(tok)
        # Expand common synonyms/abbreviations
        if tok in {"tl", "tirelait", "tire-lait", "tire_lait"}:
            out.update({"tire", "lait"})
        if tok == "ne":
            out.add("pas")  # help for 'ne fonctionne pas/plus' overlap
        if tok == "pas":
            out.add("ne")
    return out


def _expand_query_variants(text: str) -> list[str]:
    """Generate simple normalized variants to improve matching for common user phrasings."""
    t = (text or "").strip()
    if not t:
        return []
    variants = [t]
    low = t.lower()
    # unify tire-lait spelling and common abbreviations
    v = low.replace("tire-lait", "tire lait")
    v = re.sub(r"\btl\b", "tire lait", v)
    # common phrasing: 'ne fonctionne pas' vs 'ne fonctionne plus'
    v2 = v.replace("ne fonctionne pas", "ne fonctionne plus")
    # reduce articles/pronouns noise
    v3 = re.sub(r"\b(le|la|les|mon|ma|mes)\b", " ", v2)
    for cand in {v, v2, v3}:
        if cand and cand not in variants:
            variants.append(cand)
    return variants


# --------- CSV handling ---------
def _detect_delimiter_and_encoding(p: Path) -> tuple[str, str]:
    """Detect encoding and delimiter from CSV file."""
    for enc in ("utf-8", "cp1252"):
        try:
            sample = p.read_text(encoding=enc, errors='strict')[:4096]
            # Prefer semicolon if present frequently
            if sample.count(';') >= sample.count(','):
                return enc, ';'
            return enc, ','
        except Exception:
            continue
    return "utf-8", ','


def _find_qr_indices(header: list[str]) -> tuple[int | None, int | None]:
    """Find question and answer column indices from header."""
    q_idx = a_idx = None
    for i, h in enumerate(header):
        hn = _strip_accents(h)
        if q_idx is None and ('question' in hn or 'quest' in hn):
            q_idx = i
        if a_idx is None and ('reponse' in hn or 'repon' in hn or 'answer' in hn):
            a_idx = i
    return q_idx, a_idx


def _extract_qr_rows(csv_path: Path) -> list[tuple[str, str]]:
    """Extract Q&A rows from CSV file."""
    rows: list[tuple[str, str]] = []
    enc, delim = _detect_delimiter_and_encoding(csv_path)
    try:
        with csv_path.open('r', encoding=enc, newline='') as f:
            reader = csv.reader(f, delimiter=delim)
            first = True
            q_idx = a_idx = None
            for row in reader:
                if not row:
                    continue
                if first:
                    header = [c.strip() for c in row]
                    q_idx, a_idx = _find_qr_indices(header)
                    first = False
                    continue
                if q_idx is not None and a_idx is not None and len(row) > max(q_idx, a_idx):
                    q = (row[q_idx] or '').strip()
                    a = (row[a_idx] or '').strip()
                    if q and a:
                        rows.append((q, a))
                else:
                    # Fallback: take last two non-empty cells as Q/A
                    cells = [c.strip() for c in row if (c or '').strip()]
                    if len(cells) >= 2:
                        q, a = cells[-2], cells[-1]
                        if q and a:
                            rows.append((q, a))
    except Exception:
        return []
    return rows


def load_rag_csv(path_hint: str | None = None) -> None:
    """Load QR.csv and build RAG index."""
    global RAG_INDEX, LOADED_RAG_PATH
    RAG_INDEX = []
    path_str = (path_hint or RAG_CSV_PATH or "QR.csv").strip()
    csv_path = Path(path_str)
    if not csv_path.is_absolute():
        csv_path = Path(__file__).resolve().parent / csv_path
    if not csv_path.exists():
        LOADED_RAG_PATH = None
        return
    
    rows: list[tuple[str, str]] = _extract_qr_rows(csv_path)
    if not rows:
        LOADED_RAG_PATH = str(csv_path)
        return

    # Build lightweight index WITHOUT calling embeddings at startup
    for q, a in rows:
        text = f"Q: {q}\nA: {a}"
        tokens = _tokenize_norm(f"{q} {a}")
        RAG_INDEX.append({
            "q": q,
            "a": a,
            "text": text,
            "emb": [],  # lazily computed if needed
            "norm": 1.0,
            "tokens": tokens,
        })
    LOADED_RAG_PATH = str(csv_path)


def clean_rag_csv(src_path: str | None = None, dst_path: str | None = None) -> dict:
    """Clean and standardize RAG CSV to 2-column UTF-8 format."""
    src = Path(src_path or RAG_CSV_PATH or "QR.csv")
    if not src.is_absolute():
        src = Path(__file__).resolve().parent / src
    if not src.exists():
        return {"ok": False, "error": f"Source not found: {src}"}
    
    dst = Path(dst_path or (src.parent / "QR_clean.csv"))
    rows = _extract_qr_rows(src)
    if not rows:
        return {"ok": False, "error": "No Q/A rows found"}
    
    try:
        with dst.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["question", "answer"])
            writer.writerows(rows)
        return {"ok": True, "src": str(src), "dst": str(dst), "count": len(rows)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def rag_retrieve(user_query: str, k: int = 3) -> list[dict]:
    """Retrieve top K RAG documents using hybrid retrieval (embedding + lexical).

    Adds a fuzzy-text fallback (difflib) if strict lexical/embedding retrieval returns no results.
    """
    if not RAG_INDEX or not user_query:
        return []

    # Quick typo normalization for common mistypes (e.g. 'tn' instead of 'tl')
    if "tn" in user_query.lower():
        user_query = user_query.lower().replace("tn", "tl")

    # 1) Optional embedding-based retrieval
    embed_scores: list[tuple[float, dict]] = []
    top_from_embed: list[dict] = []
    if RAG_USE_EMBED:
        q_emb: list[float] | None = None
        try:
            q_emb = _embed(user_query)
        except Exception:
            q_emb = None
        if q_emb:
            for doc in RAG_INDEX:
                if doc.get("emb") == []:
                    try:
                        emb = _embed(doc.get("text", ""))
                    except Exception:
                        emb = []
                    doc["emb"] = emb
                    doc["norm"] = _vec_norm(emb) if emb else 1.0
                sim = _cosine(q_emb, doc.get("emb") or [], doc.get("norm"))
                embed_scores.append((sim, doc))
            embed_scores.sort(key=lambda x: x[0], reverse=True)
            top_from_embed = [d for (s, d) in embed_scores[:k] if s > 0]

    # 2) Lexical fallback
    STOP = {
        "le", "la", "les", "de", "des", "du", "un", "une", "et", "ou", "je", "il", "elle",
        "en", "sur", "au", "aux", "pour", "pas", "c", "ce", "se", "ne", "plus", "mon",
        "ma", "mes", "ton", "ta", "tes", "est", "que", "qui", "qu", "d", "l", "y", "a", "aujourd", "hui"
    }
    norm_q = _strip_accents(user_query)
    q_tokens = set(t for t in re.split(r"[^a-z0-9]+", norm_q) if t and t not in STOP)
    lex_scores: list[tuple[float, dict]] = []
    if q_tokens:
        for doc in RAG_INDEX:
            dt = doc.get("tokens") or set()
            inter = q_tokens & dt
            score = float(len(inter))
            if norm_q and _strip_accents(doc.get("text", "")).find(norm_q) != -1:
                score += 0.5
            if score > 0:
                lex_scores.append((score, doc))
        lex_scores.sort(key=lambda x: x[0], reverse=True)
    top_from_lex = [d for (s, d) in lex_scores[:k]] if lex_scores else []

    # 3) Fuzzy fallback: use difflib ratio on normalized text if no result yet
    if not (top_from_embed or top_from_lex):
        try:
            from difflib import SequenceMatcher
            fuzzy_scores: list[tuple[float, dict]] = []
            for doc in RAG_INDEX:
                norm_doc = _strip_accents(doc.get("text", ""))
                if not norm_doc:
                    continue
                ratio = SequenceMatcher(None, norm_q, norm_doc).ratio()
                if ratio > 0.35:
                    fuzzy_scores.append((ratio, doc))
            fuzzy_scores.sort(key=lambda x: x[0], reverse=True)
            return [d for (s, d) in fuzzy_scores[:k]]
        except Exception:
            return []

    return top_from_embed or top_from_lex


def quick_rag_answer(user_query: str) -> str | None:
    """Fast path: return answer if user query closely matches a stored Q."""
    if not RAG_INDEX or not user_query:
        return None

    # Consider simple typo variants (e.g. 'tn' -> 'tl') to improve recall
    candidates = [user_query]
    if "tn" in user_query.lower():
        candidates.insert(0, user_query.lower().replace("tn", "tl"))

    best_overall = (0.0, None)
    try:
        from difflib import SequenceMatcher
    except Exception:
        SequenceMatcher = None

    for cand in candidates:
        q_tokens = _tokenize_norm(cand)
        norm_q = _strip_accents(cand)
        best = (0.0, None)
        for doc in RAG_INDEX:
            dq = doc.get("q", "")
            dqt = _tokenize_norm(dq)
            if not dqt:
                continue
            inter = len(q_tokens & dqt)
            union = len(q_tokens | dqt) or 1
            jacc = inter / union
            norm_dq = _strip_accents(dq)
            if norm_q == norm_dq:
                jacc = 1.0
            elif norm_q and norm_dq and (norm_q in norm_dq or norm_dq in norm_q):
                jacc = max(jacc, 0.9)
            # fuzzy ratio as secondary signal
            if SequenceMatcher is not None and jacc < 0.6:
                try:
                    ratio = SequenceMatcher(None, norm_q, norm_dq).ratio()
                    jacc = max(jacc, ratio)
                except Exception:
                    pass
            if jacc > best[0]:
                best = (jacc, doc)
        # Keep the best candidate across variants
        if best[0] > best_overall[0]:
            best_overall = best

    score, doc = best_overall
    if doc and score >= 0.55:
        return doc.get("a") or None
    return None


def rag_count() -> int:
    """Return number of items in RAG index."""
    return len(RAG_INDEX)


def _maybe_translate(text: str, target_lang: str) -> str:
    """Optionally translate text to target language using LLM."""
    if not text or target_lang == "fr" or not RAG_TRANSLATE:
        return text
    try:
        tgt = {"fr": "French", "en": "English", "ar": "Arabic"}.get(target_lang, "French")
        tr = client.chat.completions.create(
            model=MODEL,
            temperature=0.0,
            messages=[
                {"role": "system", "content": f"Translate the given text to {tgt}. Keep formatting. Do not add extra text."},
                {"role": "user", "content": text},
            ],
        )
        return tr.choices[0].message.content or text
    except Exception:
        return text
