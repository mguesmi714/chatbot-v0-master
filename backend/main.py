from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import os
import re
from openai import OpenAI
import uuid
from typing import Optional

# Import RAG and language detection
from rag import load_rag_csv, rag_retrieve, rag_count
from language_detection import normalize_lang, llm_detect_language

# Setup
app = FastAPI(title="TLX Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# File uploads
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Session state
SESSION_STATE = {}

# OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Models
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[Message]
    session_id: str | None = None

class ChatResponse(BaseModel):
    reply: str
    session_id: str | None = None
    lang: str = "fr"
    intent: Optional[str] = None
    attachments: Optional[list[str]] = None
    # Optional confirmation flow payload
    confirm: bool = False
    summary: Optional[dict] = None

# Health
@app.get("/health")
async def health():
    return {"status": "ok"}

# RAG endpoints
@app.post("/rag/reload")
async def reload_rag():
    try:
        load_rag_csv()
        count = rag_count()
        return {"reloaded": True, "count": count}
    except Exception as e:
        return {"reloaded": False, "error": str(e)}

@app.post("/rag/ask")
async def rag_ask(q: str = Form(...), fallback: bool = Form(False), language: str | None = Form(None)):
    """RAG endpoint. By default returns only RAG answers; set `fallback=true` to allow LLM fallback."""
    try:
        # Helper: translate answer to requested language (fr/en/ar) if needed
        def _translate(text: str, lang_code: str | None) -> str:
            if not text or not lang_code or lang_code == "fr":
                return text
            try:
                tgt = {"fr": "French", "en": "English", "ar": "Arabic"}.get(lang_code, "French")
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

        # Determine effective language: client param > detection
        lang_eff = normalize_lang(language) if language else (llm_detect_language(q) if q else "fr")
        lang_eff = lang_eff or "fr"

        # Try RAG first
        results = rag_retrieve(q, k=3)
        found = False
        answer = ""
        matched_question = ""
        if results and results[0].get('a'):
            answer = results[0].get('a', '')
            matched_question = results[0].get('q', '')
            found = True
            # Translate answer if client requested a non-French language
            translated = _translate(answer, lang_eff)
            print(f"[RAG ASK] q={q[:80]!r} found=True matched_question={matched_question[:80]!r} fallback={fallback} lang={lang_eff}")
            return {"answer": translated, "matched_question": matched_question, "lang": lang_eff, "found": True, "used_fallback": False}

        # No RAG result
        print(f"[RAG ASK] q={q[:80]!r} found=False fallback={fallback}")
        if not fallback:
            return {"answer": "", "matched_question": "", "lang": language or "fr", "found": False, "used_fallback": False}

        # If fallback requested, use LLM
        # If fallback requested, use LLM in the requested/detected language
        tgt_lang_name = {"fr": "French", "en": "English", "ar": "Arabic"}.get(lang_eff, "French")
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": f"You are a helpful assistant for a breast pump rental company. Answer only in {tgt_lang_name}."},
                {"role": "user", "content": q}
            ],
            temperature=0.3,
        )
        answer = resp.choices[0].message.content or "Unable to answer."
        print(f"[RAG ASK] q={q[:80]!r} used_fallback=True lang={lang_eff}")
        return {"answer": answer, "matched_question": "", "lang": lang_eff, "found": False, "used_fallback": True}
    except Exception as e:
        print(f"[RAG ASK] q={q[:80]!r} error={str(e)}")
        return {"error": str(e), "answer": "An error occurred", "lang": language or "fr", "found": False, "used_fallback": False}

# Main chat endpoint
@app.post("/chat", response_model=ChatResponse)
async def chat(
    messages: str = Form(...),
    session_id: str | None = Form(None),
    language: str | None = Form(None),
    prescription_file: UploadFile | None = File(None),
    insurance_file: UploadFile | None = File(None),
):
    """Chat endpoint with RAG, language detection, and intent handling."""
    try:
        parsed = json.loads(messages)
        req = ChatRequest(
            messages=[Message(**m) for m in parsed],
            session_id=session_id,
        )
    except Exception as e:
        return ChatResponse(
            reply="[ERROR] Invalid format",
            session_id=session_id or str(uuid.uuid4()),
            lang="fr"
        )

    sid = session_id or str(uuid.uuid4())

    # Get user text
    user_text = ""
    for m in reversed(req.messages):
        if m.role == "user":
            user_text = m.content.strip()
            break

    # Language (heuristic first, then LLM detection)
    def _quick_lang(t: str | None) -> str | None:
        if not t:
            return None
        s = t.strip().lower()
        # Arabic letters present
        if any('\u0600' <= ch <= '\u06FF' for ch in s):
            return "ar"
        # Quick English cues (including strong patterns)
        strong_en = [
            "i want", "i need", "i would like", "can you", "could you",
            "buy", "purchase", "order", "return", "renew", "rent"
        ]
        if any(p in s for p in strong_en):
            return "en"
        en_cues = ["hello", "hi", "hey", "please", "thanks", "what", "how", "my", "the", "and"]
        hits = sum(1 for cue in en_cues if cue in s)
        if hits >= 2:
            return "en"
        return None

    if language:
        lang = normalize_lang(language) or "fr"
    else:
        # Prefer quick heuristic; fallback to robust detector
        lang = _quick_lang(user_text) or (llm_detect_language(user_text) if user_text else "fr") or "fr"

    # Intent detection
    def _detect_intent(text: str) -> str:
        t = (text or "").lower()
        # Handle short shorthand like 'tl' with failure words -> treat as return/issue
        if any(x in t for x in ["tl", "t.l", "t l"]) and any(x in t for x in ["ne fonctionne", "ne marche", "panne", "cassé", "cassée", "pas marche", "pas fonctionner", "ne fonctionne pas", "ne marche pas"]):
            return "return"
        if any(x in t for x in [
            # French
            "location", "louer", "tire-lait", "tire lait", "tirelait",
            # English
            "rent", "rental", "breast pump", "i want to rent", "i would like to rent",
            # Arabic
            "استئجار", "تأجير", "أريد استئجار", "أود استئجار", "شفاط"
        ]):
            return "rent"
        if any(x in t for x in [
            # French
            "renouvel", "prolong", "renouveler", "prolongation", "prolonger",
            # English
            "renew", "renewal", "extend", "extension", "i want to renew", "i would like to renew",
            # Arabic
            "تجديد", "تمديد", "أريد تجديد", "أود تجديد"
        ]):
            return "renew"
        if any(x in t for x in [
            # French
            "retour", "rendre", "renvoyer", "restituer", "je veux retourner", "je souhaite retourner",
            # English
            "return", "send back", "return item", "i want to return", "i would like to return",
            # Arabic
            "إرجاع", "إعادة", "رجوع", "أريد إرجاع", "أود إرجاع"
        ]):
            return "return"
        return "other"

    intent = _detect_intent(user_text)

    # Save files
    saved_urls = []
    try:
        if prescription_file:
            fn = f"{sid}_prescription_{os.path.basename(prescription_file.filename)}"
            path = os.path.join(UPLOAD_DIR, fn)
            with open(path, "wb") as f:
                f.write(await prescription_file.read())
            saved_urls.append(f"/uploads/{fn}")
        if insurance_file:
            fn = f"{sid}_insurance_{os.path.basename(insurance_file.filename)}"
            path = os.path.join(UPLOAD_DIR, fn)
            with open(path, "wb") as f:
                f.write(await insurance_file.read())
            saved_urls.append(f"/uploads/{fn}")
    except Exception:
        saved_urls = []

    # Get state
    state = SESSION_STATE.get(sid, {})

    # Helpers
    def _is_affirmative(t: str) -> bool:
        if not t:
            return False
        tt = t.strip().lower()
        return any(x in tt for x in ["oui", "yes", "y", "ok", "d'accord", "confirm", "confirmé", "نعم"]) or tt in {"o", "yep", "yeah"}

    def _is_negative(t: str) -> bool:
        if not t:
            return False
        tt = t.strip().lower()
        return any(x in tt for x in ["non", "no", "not", "لا"]) or tt in {"n", "nope"}

    # If user explicitly triggers an intent (button like "Location/Renouvellement/Retour"),
    # always (re)start with a confirmation question, regardless of current stage.
    if intent in {"rent", "renew", "return"} and not _is_affirmative(user_text) and not _is_negative(user_text):
        SESSION_STATE[sid] = {"intent": intent, "stage": "asked_confirm"}
        msg = (
            ("Pour confirmer, tu veux %s ?" % ("louer un tire-lait" if intent == "rent" else ("renouveler" if intent == "renew" else "retourner")))
            if lang == "fr"
            else (
                "To confirm, do you want to %s ?" % ("rent a breast pump" if intent == "rent" else ("renew" if intent == "renew" else "return"))
                if lang == "en"
                else "لتأكيد، هل تريد %s ؟" % ("استئجار شفاط" if intent == "rent" else ("تجديد" if intent == "renew" else "إرجاع"))
            )
        )
        return ChatResponse(reply=msg, session_id=sid, lang=lang)

    # If there's an ongoing session state, handle it first (so short replies like "oui" work)
    if state.get("stage") == "asked_confirm":
        prev_intent = state.get("intent")
        if _is_affirmative(user_text):
            # Switch to progressive (ligne par ligne) collection immediately
            SESSION_STATE[sid] = {"intent": prev_intent, "stage": "collect_details", "details": {"name": "", "start_date": "", "end_date": "", "postal_code": "", "attachments": []}}
            if prev_intent == "return":
                msg = (
                    "Parfait. Pour le retour, précisez le motif:\n\n• Fin d’utilisation: nous vous envoyons l’étiquette Chronopost. Confirmez votre code postal si besoin.\n• Problème/échange: envoyez EN UNE SEULE réponse: Référence de commande, Photo/vidéo du problème, 'échange' ou 'remboursement', et votre Code postal."
                    if lang == "fr"
                    else (
                        "Great. For the return, please specify the reason:\n\n• End of use: we’ll send you the Chronopost label. Confirm your postal code if needed.\n• Issue/exchange: send IN A SINGLE reply: Order reference, Photo/video of the issue, 'exchange' or 'refund', and your Postal code."
                        if lang == "en"
                        else "حسناً. بخصوص الإرجاع، حدِّد السبب:\n\n• انتهاء الاستخدام: سنرسل لك ملصق الشحن (Chronopost). أكِّد الرمز البريدي إن لزم.\n• مشكلة/استبدال: أرسل في رد واحد: مرجع الطلب، صورة/فيديو للمشكلة، 'استبدال' أو 'استرداد'، والرمز البريدي."
                    )
                )
            else:
                # First prompt for progressive flow
                if lang == "fr":
                    msg = "Merci. Indiquez Nom, Prénom (ex: Dupont, Marie)"
                elif lang == "en":
                    msg = "Thanks. Please provide Last name, First name (e.g., Doe, Jane)"
                else:
                    msg = "شكرًا. يرجى إرسال الاسم واللقب (مثال: أحمد، علي)"
            return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=saved_urls or None)
        elif _is_negative(user_text):
            SESSION_STATE.pop(sid, None)
            msg = "D'accord, annule." if lang == "fr" else ("Okay, cancelled." if lang == "en" else "حسناً، تم الإلغاء.")
            return ChatResponse(reply=msg, session_id=sid, lang=lang)
        else:
            msg = "Pour confirmer, tu veux %s ?" % ("louer un tire-lait" if prev_intent=="rent" else ("renouveler" if prev_intent=="renew" else "retourner")) if lang == "fr" else ("To confirm, do you want to %s ?" % ("rent a breast pump" if prev_intent=="rent" else ("renew" if prev_intent=="renew" else "return")) if lang == "en" else "لتأكيد، هل تريد %s ؟" % ("استئجار شفاط" if prev_intent=="rent" else ("تجديد" if prev_intent=="renew" else "إرجاع")))
            return ChatResponse(reply=msg, session_id=sid, lang=lang)

    # Progressive collection (ligne par ligne)
    if state.get("stage") == "collect_details":
        prev_intent = state.get("intent") or intent
        details = state.get("details") or {"name": "", "start_date": "", "end_date": "", "postal_code": "", "attachments": []}
        edit_mode = bool(state.get("edit"))

        # Helper parsers
        def _parse_dates(t: str):
            ds = re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", t)
            return ds

        def _parse_postal(t: str):
            m = re.search(r"\b\d{5}\b", t)
            return m.group(0) if m else ""

        def _parse_name(t: str):
            # Accept formats: "Nom, Prenom" or two words
            if "," in t:
                parts = [p.strip() for p in t.split(",") if p.strip()]
                if len(parts) >= 2:
                    return f"{parts[0]} {parts[1]}"
            parts = [p for p in re.split(r"\s+", t.strip()) if p]
            if len(parts) >= 2 and len(" ".join(parts)) <= 80:
                return f"{parts[0]} {parts[1]}"
            return ""

        # Try to map incoming text to next missing field
        missing_order = [f for f in ["name", "start_date", "end_date", "postal_code"] if not details.get(f)]
        filled = False

        # Attachments status for this turn
        if saved_urls:
            details["attachments"] = saved_urls

        # If we are in edit mode (user clicked "Modifier"), allow targeted corrections like "Nom: ...", "Date début: ...", "Code postal: 75001"
        if edit_mode:
            changed = False
            lt = (user_text or "").strip()
            if not lt:
                # Ask which field to modify
                msg = (
                    "D'accord. Quel champ souhaitez-vous corriger ?\nExemples: \n• Nom: Dupont Marie\n• Date début: 22/01/2026\n• Date fin: 29/01/2026\n• Code postal: 69001"
                    if lang == "fr"
                    else (
                        "Okay. Which field would you like to edit?\nExamples:\n• Name: Doe Jane\n• Start date: 22/01/2026\n• End date: 29/01/2026\n• Postal code: 69001"
                        if lang == "en"
                        else "حسنًا. ما الحقل الذي تريد تعديله؟\nأمثلة:\n• الاسم: أحمد علي\n• تاريخ البدء: 22/01/2026\n• تاريخ النهاية: 29/01/2026\n• الرمز البريدي: 69001"
                    )
                )
                # Persist state
                SESSION_STATE[sid] = {"intent": prev_intent, "stage": "collect_details", "details": details, "edit": True}
                return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=details.get("attachments") or None)

            def _apply_labeled_change(patterns: list[str], key: str, parser=None):
                nonlocal changed
                for p in patterns:
                    m = re.search(rf"(?i)\b{p}\b\s*:\s*(.+)", lt)
                    if m:
                        val = m.group(1).strip()
                        if key in {"start_date", "end_date"}:
                            ds = re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", val)
                            if ds:
                                details[key] = ds[0]
                                changed = True
                                return
                        elif key == "postal_code":
                            pc = re.search(r"\b\d{5}\b", val)
                            if pc:
                                details[key] = pc.group(0)
                                changed = True
                                return
                        elif key == "name":
                            nm = parser(val) if parser else val
                            if nm:
                                details[key] = nm
                                changed = True
                                return
                        else:
                            if val:
                                details[key] = val
                                changed = True
                                return

            _apply_labeled_change(["nom", "name", "الاسم"], "name", _parse_name)
            _apply_labeled_change(["date début", "date debut", "start date", "تاريخ البدء"], "start_date")
            _apply_labeled_change(["date fin", "end date", "تاريخ النهاية"], "end_date")
            _apply_labeled_change(["code postal", "postal code", "الرمز البريدي"], "postal_code")

            # Persist after possible changes
            SESSION_STATE[sid] = {"intent": prev_intent, "stage": "collect_details", "details": details, "edit": not changed}

            # If nothing recognized, ask again with examples
            if not changed:
                msg = (
                    "Je n'ai pas identifié le champ à corriger. Utilisez par ex.: 'Nom: Dupont Marie' ou 'Date début: 22/01/2026' ou 'Code postal: 69001'."
                    if lang == "fr"
                    else (
                        "I couldn't detect which field to edit. Use e.g.: 'Name: Doe Jane' or 'Start date: 22/01/2026' or 'Postal code: 69001'."
                        if lang == "en"
                        else "لم أتعرف على الحقل المراد تعديله. استخدم مثلًا: 'الاسم: أحمد علي' أو 'تاريخ البدء: 22/01/2026' أو 'الرمز البريدي: 69001'."
                    )
                )
                return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=details.get("attachments") or None)

        if missing_order:
            nxt = missing_order[0]
            if nxt == "name":
                guess = _parse_name(user_text)
                if guess:
                    details["name"] = guess
                    filled = True
            elif nxt == "start_date":
                ds = _parse_dates(user_text)
                if ds:
                    details["start_date"] = ds[0]
                    # If two dates in one line, take second as end_date
                    if len(ds) >= 2 and not details.get("end_date"):
                        details["end_date"] = ds[1]
                    filled = True
            elif nxt == "end_date":
                ds = _parse_dates(user_text)
                if ds:
                    # Take last date as end_date if any
                    details["end_date"] = ds[-1]
                    filled = True
            elif nxt == "postal_code":
                pc = _parse_postal(user_text)
                if pc:
                    details["postal_code"] = pc
                    filled = True

        # Persist details
        SESSION_STATE[sid] = {"intent": prev_intent, "stage": "collect_details", "details": details}

        # Check completion
        need_attachments = (prev_intent in {"rent", "renew"})
        have_all_fields = all(details.get(k) for k in ["name", "start_date", "end_date", "postal_code"]) and ((len(details.get("attachments", [])) >= 2) if need_attachments else True)

        if have_all_fields:
            # Build summary and confirm
            summary = {
                "name": details.get("name", ""),
                "start_date": details.get("start_date", ""),
                "end_date": details.get("end_date", ""),
                "postal_code": details.get("postal_code", ""),
                "attachments": details.get("attachments", []),
            }
            SESSION_STATE[sid] = {"intent": prev_intent, "stage": "confirm_summary", "details": summary}
            if lang == "fr":
                msg = (
                    "Merci. Voici votre récapitulatif:\n"
                    f"• Nom/Prénom: {summary['name']}\n"
                    f"• Date début: {summary['start_date']}\n"
                    f"• Date fin: {summary['end_date']}\n"
                    f"• Code postal: {summary['postal_code']}\n"
                    "• PJ: Ordonnance + Carte mutuelle\n\n"
                    "Confirmer la commande ? (Oui / Non)"
                )
            elif lang == "en":
                msg = (
                    "Thanks. Here is your summary:\n"
                    f"• Name: {summary['name']}\n"
                    f"• Start date: {summary['start_date']}\n"
                    f"• End date: {summary['end_date']}\n"
                    f"• Postal code: {summary['postal_code']}\n"
                    "• Attachments: Prescription + Insurance card\n\n"
                    "Confirm order? (Yes / No)"
                )
            else:
                msg = (
                    "شكرًا. هذا الملخص:\n"
                    f"• الاسم: {summary['name']}\n"
                    f"• تاريخ البدء: {summary['start_date']}\n"
                    f"• تاريخ النهاية: {summary['end_date']}\n"
                    f"• الرمز البريدي: {summary['postal_code']}\n"
                    "• المرفقات: الوصفة + بطاقة التأمين\n\n"
                    "تأكيد الطلب؟ (نعم / لا)"
                )
            return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=details.get("attachments") or None, confirm=True, summary=summary)

        # Otherwise prompt next field
        prompts = {
            "name": {
                "fr": "Merci. Indiquez Nom, Prénom (ex: Dupont, Marie)",
                "en": "Thanks. Please provide Last name, First name (e.g., Doe, Jane)",
                "ar": "شكرًا. يرجى إرسال الاسم واللقب (مثال: أحمد، علي)"
            },
            "start_date": {
                "fr": "Date début (ex: 22/01/2026)",
                "en": "Start date (e.g., 22/01/2026)",
                "ar": "تاريخ البدء (مثال: 22/01/2026)"
            },
            "end_date": {
                "fr": "Date fin (ex: 29/01/2026)",
                "en": "End date (e.g., 29/01/2026)",
                "ar": "تاريخ النهاية (مثال: 29/01/2026)"
            },
            "postal_code": {
                "fr": "Code postal (5 chiffres)",
                "en": "Postal code (5 digits)",
                "ar": "الرمز البريدي (5 أرقام)"
            },
            "attachments": {
                "fr": "Ajoutez les 2 pièces: Ordonnance + Carte mutuelle (PDF ou image)",
                "en": "Please attach both files: Prescription + Insurance card (PDF or image)",
                "ar": "يرجى إرفاق ملفين: الوصفة + بطاقة التأمين (PDF أو صورة)"
            }
        }

        next_missing = [f for f in ["name", "start_date", "end_date", "postal_code"] if not details.get(f)]
        if not next_missing and need_attachments and len(details.get("attachments", [])) < 2:
            key = "attachments"
        else:
            key = next_missing[0] if next_missing else "attachments"
        msg = prompts[key][lang if lang in {"fr","en","ar"} else "fr"]
        return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=details.get("attachments") or None)

    if state.get("stage") == "awaiting_details":
        prev_intent = state.get("intent")
        missing = []
        if prev_intent in {"rent", "renew"}:
            if len(user_text.split()) < 2:
                missing.append("name_firstname")
            dates_found = re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", user_text)
            if len(dates_found) < 2:
                missing.append("date_range")
            if not re.search(r"\b\d{5}\b", user_text):
                missing.append("postal_code")
            if len(saved_urls) < 2:
                missing.append("attachments")

            if missing:
                field_map = {
                    "name_firstname": "Nom + Prenom" if lang == "fr" else ("Last + First name" if lang == "en" else "اللقب + الاسم الأول"),
                    "date_range": "Date debut et date fin" if lang == "fr" else ("Start and end date" if lang == "en" else "تاريخ البدء والنهاية"),
                    "postal_code": "Code postal" if lang == "fr" else ("Postal code" if lang == "en" else "الرمز البريدي"),
                    "attachments": "Ordonnance + Carte mutuelle (PDF ou image)" if lang == "fr" else ("Prescription + Insurance card (PDF or image)" if lang == "en" else "الوصفة + بطاقة التأمين (PDF أو صورة)"),
                }
                missing_list = ", ".join(field_map.get(m, m) for m in missing)
                if lang == "fr":
                    msg = f"Merci, il manque ces informations: {missing_list}. Vous pouvez les envoyer EN UNE SEULE réponse, ou bien LIGNE PAR LIGNE.\n\nSi vous préférez: indiquez d'abord Nom/Prénom, puis Date début, Date fin, puis Code postal, et ajoutez les 2 pièces (Ordonnance + Carte mutuelle)."
                elif lang == "en":
                    msg = f"Thanks, missing info: {missing_list}. You can send them IN A SINGLE reply, or STEP BY STEP.\n\nIf you prefer: provide Name, then Start date, End date, then Postal code, and attach both files."
                else:
                    msg = f"شكرًا، المعلومات المفقودة: {missing_list}. يمكنك إرسالها في رد واحد، أو سطرًا بسطر.\n\nإن رغبت: أرسل الاسم، ثم تاريخ البدء، ثم تاريخ النهاية، ثم الرمز البريدي، ثم أرفق الملفين."

                # If user message seems to contain only a single field, switch to progressive mode directly
                looks_single = bool(re.search(r"\b\d{5}\b", user_text) or re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", user_text) or (len(user_text.split()) <= 4))
                if looks_single or ("ligne" in user_text.lower()) or ("step" in user_text.lower()) or ("line" in user_text.lower()):
                    SESSION_STATE[sid] = {"intent": prev_intent, "stage": "collect_details", "details": {"name": "", "start_date": "", "end_date": "", "postal_code": "", "attachments": saved_urls or []}}
                return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=saved_urls or None)

            # Extract a simple summary from the user's message
            # Name: take first two words of the message as an approximation
            words = [w for w in re.split(r"\s+", user_text.strip()) if w]
            name_guess = " ".join(words[:2]) if len(words) >= 2 else ""
            # Dates: take first 2 dd/mm/yyyy found
            start_date, end_date = (dates_found[0], dates_found[1]) if len(dates_found) >= 2 else ("", "")
            # Postal code
            pc_match = re.search(r"\b\d{5}\b", user_text)
            postal_code = pc_match.group(0) if pc_match else ""

            summary = {
                "name": name_guess,
                "start_date": start_date,
                "end_date": end_date,
                "postal_code": postal_code,
                "attachments": saved_urls,
            }

            # Store pending details and ask for confirmation
            SESSION_STATE[sid] = {"intent": prev_intent, "stage": "confirm_summary", "details": summary}
            if lang == "fr":
                msg = (
                    "Merci. Voici votre récapitulatif:\n"
                    f"• Nom/Prénom: {summary['name']}\n"
                    f"• Date début: {summary['start_date']}\n"
                    f"• Date fin: {summary['end_date']}\n"
                    f"• Code postal: {summary['postal_code']}\n"
                    "• PJ: Ordonnance + Carte mutuelle\n\n"
                    "Confirmer la commande ? (Oui / Non)"
                )
            elif lang == "en":
                msg = (
                    "Thanks. Here is your summary:\n"
                    f"• Name: {summary['name']}\n"
                    f"• Start date: {summary['start_date']}\n"
                    f"• End date: {summary['end_date']}\n"
                    f"• Postal code: {summary['postal_code']}\n"
                    "• Attachments: Prescription + Insurance card\n\n"
                    "Confirm order? (Yes / No)"
                )
            else:
                msg = (
                    "شكرًا. هذا الملخص:\n"
                    f"• الاسم: {summary['name']}\n"
                    f"• تاريخ البدء: {summary['start_date']}\n"
                    f"• تاريخ النهاية: {summary['end_date']}\n"
                    f"• الرمز البريدي: {summary['postal_code']}\n"
                    "• المرفقات: الوصفة + بطاقة التأمين\n\n"
                    "تأكيد الطلب؟ (نعم / لا)"
                )
            return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=saved_urls or None, confirm=True, summary=summary)

        if prev_intent == "return":
            lt = (user_text or "").lower()
            issue_words = ["ne fonctionne", "ne marche", "panne", "cass", "n'aspire", "aspire pas", "problem", "problème", "issue", "not working", "broken", "doesn't", "does not", "لا يعمل", "معطل"]
            end_words = ["fin", "fin d'utilisation", "plus besoin", "rendre", "restituer", "retour simple", "etiquette", "étiquette", "label", "chronopost", "déposer", "depot", "retourner le", "انتهاء", "إرجاع", "إعادة", "رجوع"]
            has_issue = any(w in lt for w in issue_words)
            has_end = any(w in lt for w in end_words)

            if has_end and not has_issue:
                # End-of-use return: provide procedure, no extra fields required
                SESSION_STATE.pop(sid, None)
                msg = (
                    "Très bien — retour fin d’utilisation. Le retour se fait via Chronopost : téléchargez l’étiquette sur notre site, mettez dans un carton le tire‑lait, le chargeur, le sac de transport et le pain de glace, puis déposez le colis en relais pickup/Chronopost. Besoin d’aide ? Dites-le moi et je vous renvoie le lien."
                    if lang == "fr"
                    else (
                        "Got it — end-of-use return. Please use the Chronopost label from our website, put the breast pump, charger, transport bag and ice pack in a box, then drop it at a pickup/Chronopost location. Need help? I can resend the link."
                        if lang == "en"
                        else "حسناً — إرجاع لانتهاء الاستخدام. استخدم ملصق Chronopost من موقعنا، وضع الجهاز مع الشاحن وحقيبة النقل وقطعة الثلج في صندوق، ثم سلِّم الطرد في نقطة استلام. إن احتجت الرابط أخبرني."
                    )
                )
                return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent)

            # Issue/exchange flow: expect order ref, choice, and a photo
            opt_missing = []
            if not re.search(r"\b[A-Za-z0-9\-]{4,}\b", user_text):
                opt_missing.append("order_reference")
            if not any(x in lt for x in ["echange", "échange", "remboursement", "exchange", "refund", "rembourse"]):
                opt_missing.append("choice")
            if len(saved_urls) < 1:
                opt_missing.append("photo")

            if opt_missing:
                field_map = {
                    "order_reference": "Référence de commande" if lang == "fr" else ("Order reference" if lang == "en" else "مرجع الطلب"),
                    "choice": "Échange ou remboursement" if lang == "fr" else ("Exchange or refund" if lang == "en" else "استبدال أو استرداد"),
                    "photo": "Photo/vidéo du problème" if lang == "fr" else ("Photo/video of the issue" if lang == "en" else "صورة/فيديو للمشكلة"),
                }
                missing_list = ", ".join(field_map.get(m, m) for m in opt_missing)
                msg = (f"Merci, il manque ces informations pour le retour: {missing_list}. Merci de les envoyer EN UNE SEULE reponse." if lang == "fr" else (f"Thanks, missing info for return: {missing_list}. Please send them IN A SINGLE reply." if lang == "en" else f"شكرًا، المعلومات المفقودة للعودة: {missing_list}. يرجى إرسالها في رد واحد."))
                return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=saved_urls or None)

            SESSION_STATE.pop(sid, None)
            msg = ("Nous avons bien reçu votre dossier. Nous procédons à l'envoi d'un nouveau tire-lait et vous enverrons les détails d'expédition par email/sms sous 24h." if lang == "fr" else ("We received your case. We'll send a replacement pump and provide shipping details via email/sms within 24h." if lang == "en" else "لقد استلمنا ملفك. سنرسل جهازًا بديلاً ونوافيك بتفاصيل الشحن خلال 24 ساعة."))
            return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent)

    # Intent flow (start new intent if no ongoing state)
    if intent in {"rent", "renew", "return"}:
        # Handle confirmation of summary if pending
        if state.get("stage") == "confirm_summary":
            prev_intent = state.get("intent")
            if _is_affirmative(user_text):
                SESSION_STATE.pop(sid, None)
                msg = (
                    "Parfait — nous avons bien recu votre demande de location avec les informations et pieces jointes. Nous procedons a la reservation et revenons vers vous sous 24h."
                    if lang == "fr"
                    else (
                        "Perfect — we received your rental request with all details and attachments. We'll proceed and get back within 24h."
                        if lang == "en"
                        else "ممتاز — لقد استلمنا طلب الاستئجار بكل البيانات والمرفقات. سنقوم بالإجراءات ونعود إليك خلال 24 ساعة."
                    )
                )
                return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent)
            if _is_negative(user_text):
                # Switch to edit mode in progressive collection with pre-filled details
                current = state.get("details") or {"name": "", "start_date": "", "end_date": "", "postal_code": "", "attachments": []}
                SESSION_STATE[sid] = {"intent": prev_intent, "stage": "collect_details", "details": current, "edit": True}
                msg = (
                    "D'accord. Quel champ souhaitez-vous corriger ?\nExemples: \n• Nom: Dupont Marie\n• Date début: 22/01/2026\n• Date fin: 29/01/2026\n• Code postal: 69001"
                    if lang == "fr"
                    else (
                        "Okay. Which field would you like to edit?\nExamples:\n• Name: Doe Jane\n• Start date: 22/01/2026\n• End date: 29/01/2026\n• Postal code: 69001"
                        if lang == "en"
                        else "حسنًا. ما الحقل الذي تريد تعديله؟\nأمثلة:\n• الاسم: أحمد علي\n• تاريخ البدء: 22/01/2026\n• تاريخ النهاية: 29/01/2026\n• الرمز البريدي: 69001"
                    )
                )
                return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=current.get("attachments") or None)

            # Inline corrections while on the recap
            current = state.get("details") or {"name": "", "start_date": "", "end_date": "", "postal_code": "", "attachments": []}
            lt = (user_text or "").strip()
            changed = False

            def _apply_labeled_change_cs(patterns: list[str], key: str, parser=None):
                nonlocal changed
                for p in patterns:
                    m = re.search(rf"(?i)\b{p}\b\s*:\s*(.+)", lt)
                    if m:
                        val = m.group(1).strip()
                        if key in {"start_date", "end_date"}:
                            ds = re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", val)
                            if ds:
                                current[key] = ds[0]
                                changed = True
                                return
                        elif key == "postal_code":
                            pc = re.search(r"\b\d{5}\b", val)
                            if pc:
                                current[key] = pc.group(0)
                                changed = True
                                return
                        elif key == "name":
                            nm = parser(val) if parser else val
                            if nm:
                                current[key] = nm
                                changed = True
                                return
                        else:
                            if val:
                                current[key] = val
                                changed = True
                                return

            def _parse_name_inline(t: str):
                if "," in t:
                    parts = [p.strip() for p in t.split(",") if p.strip()]
                    if len(parts) >= 2:
                        return f"{parts[0]} {parts[1]}"
                parts = [p for p in re.split(r"\s+", t.strip()) if p]
                if len(parts) >= 2 and len(" ".join(parts)) <= 80:
                    return f"{parts[0]} {parts[1]}"
                return ""

            _apply_labeled_change_cs(["nom", "name", "الاسم"], "name", _parse_name_inline)
            _apply_labeled_change_cs(["date début", "date debut", "start date", "تاريخ البدء"], "start_date")
            _apply_labeled_change_cs(["date fin", "end date", "تاريخ النهاية"], "end_date")
            _apply_labeled_change_cs(["code postal", "postal code", "الرمز البريدي"], "postal_code")

            if changed:
                summary = {
                    "name": current.get("name", ""),
                    "start_date": current.get("start_date", ""),
                    "end_date": current.get("end_date", ""),
                    "postal_code": current.get("postal_code", ""),
                    "attachments": current.get("attachments", []),
                }
                SESSION_STATE[sid] = {"intent": prev_intent, "stage": "confirm_summary", "details": summary}
                return ChatResponse(reply="", session_id=sid, lang=lang, intent=prev_intent, attachments=summary.get("attachments") or None, confirm=True, summary=summary)

        if state.get("stage") == "asked_confirm":
            if _is_affirmative(user_text):
                # Progressive collection directly
                SESSION_STATE[sid] = {"intent": intent, "stage": "collect_details", "details": {"name": "", "start_date": "", "end_date": "", "postal_code": "", "attachments": []}}
                if intent == "return":
                    msg = "Pour le retour, envoie votre reference de commande et la preuve d'envoi ou l'etiquette, et ajoute la photo si possible." if lang == "fr" else ("For the return, send your order reference and the shipping proof or label, and add a photo if possible." if lang == "en" else "لعملية الإرجاع، أرسل مرجع الطلب وإثبات الشحن أو الملصق، وأضف صورة إن أمكن.")
                else:
                    if lang == "fr":
                        msg = "Merci. Indiquez Nom, Prénom (ex: Dupont, Marie)"
                    elif lang == "en":
                        msg = "Thanks. Please provide Last name, First name (e.g., Doe, Jane)"
                    else:
                        msg = "شكرًا. يرجى إرسال الاسم واللقب (مثال: أحمد، علي)"
                return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=intent, attachments=saved_urls or None)
            elif _is_negative(user_text):
                SESSION_STATE.pop(sid, None)
                msg = "D'accord, annule." if lang == "fr" else ("Okay, cancelled." if lang == "en" else "حسناً، تم الإلغاء.")
                return ChatResponse(reply=msg, session_id=sid, lang=lang)
            else:
                msg = "Pour confirmer, tu veux %s ?" % ("louer un tire-lait" if intent=="rent" else ("renouveler" if intent=="renew" else "retourner")) if lang == "fr" else ("To confirm, do you want to %s ?" % ("rent a breast pump" if intent=="rent" else ("renew" if intent=="renew" else "return")) if lang == "en" else "لتأكيد، هل تريد %s ؟" % ("استئجار شفاط" if intent=="rent" else ("تجديد" if intent=="renew" else "إرجاع")))
                return ChatResponse(reply=msg, session_id=sid, lang=lang)

        # Awaiting details
        if state.get("stage") == "awaiting_details":
            missing = []
            if intent in {"rent", "renew"}:
                # Check: Nom + Prenom (at least 2 words)
                if len(user_text.split()) < 2:
                    missing.append("name_firstname")
                # Check: 2 dates (debut et fin)
                dates_found = re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", user_text)
                if len(dates_found) < 2:
                    missing.append("date_range")
                # Check: Code postal (5 digits)
                if not re.search(r"\b\d{5}\b", user_text):
                    missing.append("postal_code")
                # Check: 2 files attached
                if len(saved_urls) < 2:
                    missing.append("attachments")

                if missing:
                    field_map = {
                        "name_firstname": "Nom + Prenom" if lang == "fr" else ("Last + First name" if lang == "en" else "اللقب + الاسم الأول"),
                        "date_range": "Date debut et date fin" if lang == "fr" else ("Start and end date" if lang == "en" else "تاريخ البدء والنهاية"),
                        "postal_code": "Code postal" if lang == "fr" else ("Postal code" if lang == "en" else "الرمز البريدي"),
                        "attachments": "Ordonnance + Carte mutuelle (PDF ou image)" if lang == "fr" else ("Prescription + Insurance card (PDF or image)" if lang == "en" else "الوصفة + بطاقة التأمين (PDF أو صورة)"),
                    }
                    missing_list = ", ".join(field_map.get(m, m) for m in missing)
                    msg = f"Merci, il manque ces informations: {missing_list}. Merci de les envoyer EN UNE SEULE reponse." if lang == "fr" else (f"Thanks, missing info: {missing_list}. Please send them IN A SINGLE reply." if lang == "en" else f"شكرًا، المعلومات المفقودة: {missing_list}. يرجى إرسالها في رد واحد.")
                    return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=intent, attachments=saved_urls or None)

                SESSION_STATE.pop(sid, None)
                msg = "Parfait — nous avons bien recu votre demande de location avec les informations et pieces jointes. Nous procedons a la reservation et revenons vers vous sous 24h." if lang == "fr" else ("Perfect — we received your rental request with all details and attachments. We'll proceed and get back within 24h." if lang == "en" else "ممتاز — لقد استلمنا طلب الاستئجار بكل البيانات والمرفقات. سنقوم بالإجراءات ونعود إليك خلال 24 ساعة.")
                return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=intent)

        # Default: ask confirmation (when new intent detected)
        SESSION_STATE[sid] = {"intent": intent, "stage": "asked_confirm"}
        msg = "Pour confirmer, tu veux %s ?" % ("louer un tire-lait" if intent=="rent" else ("renouveler" if intent=="renew" else "retourner")) if lang == "fr" else ("To confirm, do you want to %s ?" % ("rent a breast pump" if intent=="rent" else ("renew" if intent=="renew" else "return")) if lang == "en" else "لتأكيد، هل تريد %s ؟" % ("استئجار شفاط" if intent=="rent" else ("تجديد" if intent=="renew" else "إرجاع")))
        return ChatResponse(reply=msg, session_id=sid, lang=lang)

    # Regular chat: RAG + LLM fallback (no intent or intent flow completed)
    rag_results = []
    rag_answer = None
    
    # Try RAG first
    if user_text:
        try:
            rag_results = rag_retrieve(user_text, k=3)
            if rag_results and rag_results[0].get('a'):
                rag_answer = rag_results[0].get('a')
        except Exception:
            rag_results = []
    
    # If RAG found a good answer, return it
    if rag_answer:
        return ChatResponse(reply=rag_answer, session_id=sid, lang=lang)
    
    # Otherwise, use LLM with RAG context
    messages_for_openai = []
    lang_name = {"fr": "Francais", "en": "English", "ar": "Arabic"}.get(lang, "Francais")
    messages_for_openai.append({
        "role": "system",
        "content": f"You are a helpful assistant for a breast pump rental company. Reply ONLY in {lang_name}. Be concise and friendly."
    })

    # Add RAG context to LLM
    if rag_results:
        kb_text = "\n".join([f"Q: {r.get('q')}\nA: {r.get('a')}" for r in rag_results[:2] if r.get('a')])
        if kb_text:
            messages_for_openai.append({
                "role": "system",
                "content": f"Reference information:\n{kb_text}"
            })

    messages_for_openai += [{"role": m.role, "content": m.content} for m in req.messages]

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages_for_openai,
            temperature=0.3,
        )
        reply = resp.choices[0].message.content or "I cannot provide an answer at this time."
        return ChatResponse(reply=reply, session_id=sid, lang=lang)
    except Exception as e:
        return ChatResponse(
            reply="Sorry, I encountered an error. Please try again.",
            session_id=sid,
            lang=lang
        )

if __name__ == "__main__":
    import uvicorn
    print("[*] Starting server...")
    load_rag_csv()
    print("[OK] RAG index loaded")
    uvicorn.run(app, host="127.0.0.1", port=8000)
