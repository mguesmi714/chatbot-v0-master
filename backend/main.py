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
            SESSION_STATE[sid] = {"intent": prev_intent, "stage": "awaiting_details"}
            if prev_intent == "rent":
                msg = "Merci de m'envoyer vos donnees en une seule reponse :\n\nNom, Prenom, Date debut (ex: 22/01/2026), Date fin (ex: 29/01/2026), Code postal\n\nEt les 2 fichiers a mettre (PDF ou image) : Ordonnance + Carte mutuelle" if lang == "fr" else ("Please send me your information in a single response:\n\nLast name, First name, Start date (e.g. 22/01/2026), End date (e.g. 29/01/2026), Postal code\n\nAnd the 2 files (PDF or image): Prescription + Insurance card" if lang == "en" else "يرجى إرسال معلوماتك في رد واحد:\n\nاللقب، الاسم الأول، تاريخ البدء (مثال: 22/01/2026)، تاريخ النهاية (مثال: 29/01/2026)، الرمز البريدي\n\nوالملفان (PDF أو صورة): الوصفة + بطاقة التأمين")
            elif prev_intent == "renew":
                msg = "Merci de m'envoyer vos donnees en une seule reponse :\n\nNom, Prenom, Date debut (ex: 22/01/2026), Date fin (ex: 29/01/2026), Code postal\n\nEt les 2 fichiers a mettre (PDF ou image) : Ordonnance + Carte mutuelle" if lang == "fr" else ("Please send me your information in a single response:\n\nLast name, First name, Start date (e.g. 22/01/2026), End date (e.g. 29/01/2026), Postal code\n\nAnd the 2 files (PDF or image): Prescription + Insurance card" if lang == "en" else "يرجى إرسال معلوماتك في رد واحد:\n\nاللقب، الاسم الأول، تاريخ البدء (مثال: 22/01/2026)، تاريخ النهاية (مثال: 29/01/2026)، الرمز البريدي\n\nوالملفان (PDF أو صورة): الوصفة + بطاقة التأمين")
            else:
                msg = (
                    "Parfait. Pour le retour, précisez le motif:\n\n• Fin d’utilisation: nous vous envoyons l’étiquette Chronopost. Confirmez votre code postal si besoin.\n• Problème/échange: envoyez EN UNE SEULE réponse: Référence de commande, Photo/vidéo du problème, 'échange' ou 'remboursement', et votre Code postal."
                    if lang == "fr"
                    else (
                        "Great. For the return, please specify the reason:\n\n• End of use: we’ll send you the Chronopost label. Confirm your postal code if needed.\n• Issue/exchange: send IN A SINGLE reply: Order reference, Photo/video of the issue, 'exchange' or 'refund', and your Postal code."
                        if lang == "en"
                        else "حسناً. بخصوص الإرجاع، حدِّد السبب:\n\n• انتهاء الاستخدام: سنرسل لك ملصق الشحن (Chronopost). أكِّد الرمز البريدي إن لزم.\n• مشكلة/استبدال: أرسل في رد واحد: مرجع الطلب، صورة/فيديو للمشكلة، 'استبدال' أو 'استرداد'، والرمز البريدي."
                    )
                )
            return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=saved_urls or None)
        elif _is_negative(user_text):
            SESSION_STATE.pop(sid, None)
            msg = "D'accord, annule." if lang == "fr" else ("Okay, cancelled." if lang == "en" else "حسناً، تم الإلغاء.")
            return ChatResponse(reply=msg, session_id=sid, lang=lang)
        else:
            msg = "Pour confirmer, tu veux %s ?" % ("louer un tire-lait" if prev_intent=="rent" else ("renouveler" if prev_intent=="renew" else "retourner")) if lang == "fr" else ("To confirm, do you want to %s ?" % ("rent a breast pump" if prev_intent=="rent" else ("renew" if prev_intent=="renew" else "return")) if lang == "en" else "لتأكيد، هل تريد %s ؟" % ("استئجار شفاط" if prev_intent=="rent" else ("تجديد" if prev_intent=="renew" else "إرجاع")))
            return ChatResponse(reply=msg, session_id=sid, lang=lang)

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
                msg = f"Merci, il manque ces informations: {missing_list}. Merci de les envoyer EN UNE SEULE reponse." if lang == "fr" else (f"Thanks, missing info: {missing_list}. Please send them IN A SINGLE reply." if lang == "en" else f"شكرًا، المعلومات المفقودة: {missing_list}. يرجى إرسالها في رد واحد.")
                return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent, attachments=saved_urls or None)

            SESSION_STATE.pop(sid, None)
            msg = "Parfait — nous avons bien recu votre demande de location avec les informations et pieces jointes. Nous procedons a la reservation et revenons vers vous sous 24h." if lang == "fr" else ("Perfect — we received your rental request with all details and attachments. We'll proceed and get back within 24h." if lang == "en" else "ممتاز — لقد استلمنا طلب الاستئجار بكل البيانات والمرفقات. سنقوم بالإجراءات ونعود إليك خلال 24 ساعة.")
            return ChatResponse(reply=msg, session_id=sid, lang=lang, intent=prev_intent)

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
        if state.get("stage") == "asked_confirm":
            if _is_affirmative(user_text):
                SESSION_STATE[sid] = {"intent": intent, "stage": "awaiting_details"}
                if intent == "rent":
                    msg = "Merci de m'envoyer vos donnees en une seule reponse :\n\nNom, Prenom, Date debut (ex: 22/01/2026), Date fin (ex: 29/01/2026), Code postal\n\nEt les 2 fichiers a mettre (PDF ou image) : Ordonnance + Carte mutuelle" if lang == "fr" else ("Please send me your information in a single response:\n\nLast name, First name, Start date (e.g. 22/01/2026), End date (e.g. 29/01/2026), Postal code\n\nAnd the 2 files (PDF or image): Prescription + Insurance card" if lang == "en" else "يرجى إرسال معلوماتك في رد واحد:\n\nاللقب، الاسم الأول، تاريخ البدء (مثال: 22/01/2026)، تاريخ النهاية (مثال: 29/01/2026)، الرمز البريدي\n\nوالملفان (PDF أو صورة): الوصفة + بطاقة التأمين")
                elif intent == "renew":
                    msg = "Merci de m'envoyer vos donnees en une seule reponse :\n\nNom, Prenom, Date debut (ex: 22/01/2026), Date fin (ex: 29/01/2026), Code postal\n\nEt les 2 fichiers a mettre (PDF ou image) : Ordonnance + Carte mutuelle" if lang == "fr" else ("Please send me your information in a single response:\n\nLast name, First name, Start date (e.g. 22/01/2026), End date (e.g. 29/01/2026), Postal code\n\nAnd the 2 files (PDF or image): Prescription + Insurance card" if lang == "en" else "يرجى إرسال معلوماتك في رد واحد:\n\nاللقب، الاسم الأول، تاريخ البدء (مثال: 22/01/2026)، تاريخ النهاية (مثال: 29/01/2026)، الرمز البريدي\n\nوالملفان (PDF أو صورة): الوصفة + بطاقة التأمين")
                else:
                    msg = "Pour le retour, envoie votre reference de commande et la preuve d'envoi ou l'etiquette, et ajoute la photo si possible." if lang == "fr" else ("For the return, send your order reference and the shipping proof or label, and add a photo if possible." if lang == "en" else "لعملية الإرجاع، أرسل مرجع الطلب وإثبات الشحن أو الملصق، وأضف صورة إن أمكن.")
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
