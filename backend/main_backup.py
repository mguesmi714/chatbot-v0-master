from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import os
import re
from openai import OpenAI
import uuid
from typing import Optional

# Import RAG and language detection modules
from rag import load_rag_csv, rag_retrieve, rag_count
from language_detection import normalize_lang, llm_detect_language

app = FastAPI(title="TLX Backend - Simple Chat")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded files from /uploads
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Simple in-memory session state to track intent confirmation / detail collection
SESSION_STATE: dict = {}

# OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Pydantic models
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

# ===== RAG ENDPOINTS =====

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}

@app.post("/rag/reload")
async def reload_rag():
    """Reload RAG index from CSV."""
    try:
        load_rag_csv()
        count = rag_count()
        return {"reloaded": True, "count": count}
    except Exception as e:
        return {"reloaded": False, "error": str(e)}

@app.post("/rag/ask")
async def rag_ask(q: str = Form(...)):
    """Ask RAG to find relevant Q&A."""
    try:
        results = rag_retrieve(q, k=3)
        if results:
            answer = results[0].get("a", "")
            question = results[0].get("q", "")
            lang = "fr"
            return {
                "answer": answer,
                "matched_question": question,
                "lang": lang
            }
        return {
            "answer": "Aucune réponse trouvée dans la base.",
            "matched_question": "",
            "lang": "fr"
        }
    except Exception as e:
        return {"error": str(e), "lang": "fr"}

# ===== CHAT ENDPOINT =====

@app.post("/chat", response_model=ChatResponse)
async def chat(
    messages: str = Form(...),
    session_id: str | None = Form(None),
    language: str | None = Form(None),
    prescription_file: UploadFile | None = File(None),
    insurance_file: UploadFile | None = File(None),
):
    """Simple chat endpoint with RAG and language detection.

    This endpoint also performs lightweight intent detection (rent/renew/return)
    and returns an immediate canned reply + any uploaded attachments URLs when
    an intent is recognized. RAG logic is not modified.
    """
    try:
        parsed = json.loads(messages)
        req = ChatRequest(
            messages=[Message(**m) for m in parsed],
            session_id=session_id,
        )
    except Exception:
        return ChatResponse(
            reply="[ERROR] Erreur: format invalide",
            session_id=session_id or str(uuid.uuid4()),
            lang="fr"
        )

    sid = session_id or str(uuid.uuid4())

    # Get user's last message
    user_text = ""
    for m in reversed(req.messages):
        if m.role == "user":
            user_text = m.content.strip()
            break

    # Language detection
    if language:
        lang = normalize_lang(language) or "fr"
    else:
        lang = llm_detect_language(user_text) if user_text else "fr"

    # Lightweight intent detection (do not modify RAG)
    def _detect_intent(text: str) -> str:
        t = (text or "").lower()
        if any(x in t for x in ["location", "louer", "tire-lait", "tire lait", "rent", "rental", "breast pump", "استئجار", "تأجير"]):
            return "rent"
        if any(x in t for x in ["renouvel", "prolong", "renouveler", "renew", "renewal", "تجديد", "تمديد"]):
            return "renew"
        if any(x in t for x in ["retour", "rendre", "renvoyer", "return", "send back", "إرجاع", "إعادة"]):
            return "return"
        return "other"

    intent = _detect_intent(user_text)

    # Save uploaded files (if any) and return accessible URLs
    saved_urls: list[str] = []
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
    # Intent flow: require confirmation then collect details
    # SESSION_STATE stores per-sid dict: {intent: str, stage: str}
    state = SESSION_STATE.get(sid, {})

    # helper to check affirmative / negative
    def _is_affirmative(t: str) -> bool:
        if not t:
            return False
        tt = t.strip().lower()
        return any(x in tt for x in ["oui", "yes", "y", "ok", "d'accord", "confirm", "confirmé", "نعم", "نعم"]) or tt in {"o", "yep", "yeah"}

    def _is_negative(t: str) -> bool:
        if not t:
            return False
        tt = t.strip().lower()
        return any(x in tt for x in ["non", "no", "not", "لا"]) or tt in {"n", "nope"}

    if intent in {"rent", "renew", "return"}:
        # If we previously asked for confirmation
        if state.get("stage") == "asked_confirm":
            if _is_affirmative(user_text):
                # move to awaiting details
                SESSION_STATE[sid] = {"intent": intent, "stage": "awaiting_details"}
                if intent == "rent":
                    # Ask for: firstname, lastname, phone, postal_code, start_date + 2 files
                    reply = {
                        "fr": "Parfait ! Pour procéder à la location, pourrais-tu me fournir les informations suivantes :\n\n1. Prénom\n2. Nom\n3. Téléphone\n4. Code postal\n5. Date de début souhaitée (ex: 22/01/2026)\n\nEt ajoute les 2 pièces jointes : Ordonnance + Carte mutuelle\n\nMerci !",
                        "en": "Great! To proceed with the rental, please provide:\n\n1) First name\n2) Last name\n3) Phone number\n4) Postal code\n5) Desired start date (e.g. 22/01/2026)\n\nAnd attach: Prescription + Insurance card\n\nThanks!",
                        "ar": "ممتاز! للمضي قدما في الاستئجار، يرجى تزويدنا بـ:\n\n1) الاسم الأول\n2) اللقب\n3) رقم الهاتف\n4) الرمز البريدي\n5) تاريخ البدء المطلوب (مثال: 22/01/2026)\n\nوأرفق: الوصفة + بطاقة التأمين\n\nشكراً",
                    }[lang if lang in {"fr", "en", "ar"} else "fr"]
                elif intent == "renew":
                    reply = {
                        "fr": "Pour le renouvellement, envoie la nouvelle ordonnance (ou preuve) et ta référence client, et ajoute la carte mutuelle.",
                        "en": "For renewal, send the new prescription (or proof) and your client reference, and add the insurance card.",
                        "ar": "للتجديد، أرسل الوصفة الجديدة (أو الإثبات) ومرجع العميل، وأضف بطاقة التأمين.",
                    }[lang if lang in {"fr", "en", "ar"} else "fr"]
                else:
                    reply = {
                        "fr": "Pour le retour, envoie votre référence de commande et la preuve d'envoi ou l'étiquette, et ajoute la photo si possible.",
                        "en": "For the return, send your order reference and the shipping proof or label, and add a photo if possible.",
                        "ar": "لعملية الإرجاع، أرسل مرجع الطلب وإثبات الشحن أو الملصق، وأضف صورة إن أمكن.",
                    }[lang if lang in {"fr", "en", "ar"} else "fr"]
                return ChatResponse(reply=reply, session_id=sid, lang=lang, intent=intent, attachments=saved_urls or None)
            elif _is_negative(user_text):
                SESSION_STATE.pop(sid, None)
                msg = "D'accord, annulé." if lang == "fr" else ("Okay, cancelled." if lang == "en" else "حسناً، تم الإلغاء.")
                return ChatResponse(reply=msg, session_id=sid, lang=lang)
            else:
                # Re-ask confirmation
                msg = "Pour confirmer, tu veux %s ?" % ("louer un tire-lait" if intent=="rent" else ("renouveler" if intent=="renew" else "retourner")) if lang == "fr" else ("To confirm, do you want to %s ?" % ("rent a breast pump" if intent=="rent" else ("renew" if intent=="renew" else "return")) if lang == "en" else "لتأكيد، هل تريد %s ؟" % ("استئجار شفاط" if intent=="rent" else ("تجديد" if intent=="renew" else "إرجاع")))
                return ChatResponse(reply=msg, session_id=sid, lang=lang)

        # If we are awaiting details
        if state.get("stage") == "awaiting_details":
            missing = []
            if intent == "rent":
                # Expect: firstname, lastname, phone, postal_code, start_date + 2 files
                # Check for firstname + lastname (at least 2 words)
                if len(user_text.split()) < 2:
                    missing.append("firstname_lastname")
                # Check for phone
                if not re.search(r"\+?\d[\d\s.-]{5,}\d", user_text):
                    missing.append("phone")
                # Check for postal code (5 digits)
                if not re.search(r"\b\d{5}\b", user_text):
                    missing.append("postal_code")
                # Check for date dd/mm/yyyy or dd/mm/yy
                if not re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", user_text):
                    missing.append("start_date")
                # Check for 2 files attached
                if len(saved_urls) < 2:
                    missing.append("attachments")

                if missing:
                    field_map = {
                        "firstname_lastname": {"fr": "Prénom + Nom", "en": "First + Last name", "ar": "الاسم الأول + اللقب"}[lang if lang in {"fr","en","ar"} else "fr"],
                        "phone": {"fr": "Téléphone", "en": "Phone", "ar": "الهاتف"}[lang if lang in {"fr","en","ar"} else "fr"],
                        "postal_code": {"fr": "Code postal", "en": "Postal code", "ar": "الرمز البريدي"}[lang if lang in {"fr","en","ar"} else "fr"],
                        "start_date": {"fr": "Date de début", "en": "Start date", "ar": "تاريخ البدء"}[lang if lang in {"fr","en","ar"} else "fr"],
                        "attachments": {"fr": "Ordonnance + Carte mutuelle", "en": "Prescription + Insurance card", "ar": "الوصفة + بطاقة التأمين"}[lang if lang in {"fr","en","ar"} else "fr"],
                    }
                    missing_list = ", ".join(field_map[m] for m in missing)
                    return ChatResponse(reply={"fr": f"Merci, il manque ces informations: {missing_list}. Merci de les envoyer EN UNE SEULE réponse.", "en": f"Thanks, missing info: {missing_list}. Please send them IN A SINGLE reply.", "ar": f"شكرًا، المعلومات المفقودة: {missing_list}. يرجى إرسالها في رد واحد."}[lang if lang in {"fr","en","ar"} else "fr"], session_id=sid, lang=lang, intent=intent, attachments=saved_urls or None)

                # All good: finalize rental
                SESSION_STATE.pop(sid, None)
                return ChatResponse(reply={
                    "fr": "Parfait — nous avons bien reçu votre demande de location avec les informations et pièces jointes. Nous procédons à la réservation et revenons vers vous sous 24h.",
                    "en": "Perfect — we received your rental request with all details and attachments. We'll proceed and get back within 24h.",
                    "ar": "ممتاز — لقد استلمنا طلب الاستئجار بكل البيانات والمرفقات. سنقوم بالإجراءات ونعود إليك خلال 24 ساعة.",
                }[lang if lang in {"fr","en","ar"} else "fr"], session_id=sid, lang=lang, intent=intent)
            else:
                # previous generic checks for renew/return
                missing = []
                if not re.search(r"\b[\p{L}]+\s+[\p{L}]+\b", user_text, flags=re.UNICODE):
                    if len(user_text.split()) < 2:
                        missing.append("name")
                if not re.search(r"\+?\d[\d\s.-]{5,}\d", user_text):
                    missing.append("phone")
                if not re.search(r"\b\d{5}\b", user_text):
                    missing.append("postal_code")
                if not re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", user_text):
                    missing.append("start_date")

                # If attachments missing, prompt upload
                if intent == "rent" and len(saved_urls) < 2:
                    return ChatResponse(reply={"fr": "Il manque les pièces jointes. Merci d'ajouter l'ordonnance et la carte mutuelle via l'interface.", "en": "Missing attachments. Please add the prescription and insurance card via the interface.", "ar": "الملفات مفقودة. يرجى إضافة الوصفة وبطاقة التأمين عبر الواجهة."}[lang if lang in {"fr","en","ar"} else "fr"], session_id=sid, lang=lang, intent=intent, attachments=saved_urls or None)

                if missing:
                    field_map = {"name": {"fr": "Prénom+Nom", "en": "First+Last name", "ar": "الاسم واللقب"}[lang if lang in {"fr","en","ar"} else "fr"],
                                 "phone": {"fr": "Téléphone", "en": "Phone", "ar": "الهاتف"}[lang if lang in {"fr","en","ar"} else "fr"],
                                 "postal_code": {"fr": "Code postal", "en": "Postal code", "ar": "الرمز البريدي"}[lang if lang in {"fr","en","ar"} else "fr"],
                                 "start_date": {"fr": "Date de début", "en": "Start date", "ar": "تاريخ البدء"}[lang if lang in {"fr","en","ar"} else "fr"]}
                    missing_list = ", ".join(field_map[m] for m in missing)
                    return ChatResponse(reply={"fr": f"Merci, il manque ces informations: {missing_list}. Merci de les envoyer EN UNE SEULE réponse.", "en": f"Thanks, missing info: {missing_list}. Please send them IN A SINGLE reply.", "ar": f"شكرًا، المعلومات المفقودة: {missing_list}. يرجى إرسالها في رد واحد."}[lang if lang in {"fr","en","ar"} else "fr"], session_id=sid, lang=lang, intent=intent, attachments=saved_urls or None)

                # All good: finalize
                SESSION_STATE.pop(sid, None)
                return ChatResponse(reply={"fr": "Merci, nous avons reçu vos informations et pièces jointes. Nous traitons votre demande et revenons vers vous sous 24h.", "en": "Thanks, we received your details and attachments. We'll process your request and get back within 24h.", "ar": "شكراً، لقد استلمنا معلوماتك والمرفقات. سنقوم بمعالجة طلبك ونعود إليك خلال 24 ساعة."}[lang if lang in {"fr","en","ar"} else "fr"], session_id=sid, lang=lang, intent=intent, attachments=saved_urls or None)

        # Default: ask for confirmation first
        SESSION_STATE[sid] = {"intent": intent, "stage": "asked_confirm"}
        msg = "Pour confirmer, tu veux %s ?" % ("louer un tire-lait" if intent=="rent" else ("renouveler" if intent=="renew" else "retourner")) if lang == "fr" else ("To confirm, do you want to %s ?" % ("rent a breast pump" if intent=="rent" else ("renew" if intent=="renew" else "return")) if lang == "en" else "لتأكيد، هل تريد %s ؟" % ("استئجار شفاط" if intent=="rent" else ("تجديد" if intent=="renew" else "إرجاع")))
        return ChatResponse(reply=msg, session_id=sid, lang=lang)

    # Build messages for OpenAI with RAG knowledge
    messages_for_openai = []

    # Language policy
    lang_name = {"fr": "Français", "en": "Anglais", "ar": "Arabe"}.get(lang, "Français")
    messages_for_openai.append({
        "role": "system",
        "content": f"Tu es un assistant utile. Réponds UNIQUEMENT en {lang_name}. Sois concis et aimable."
    })

    # Add RAG knowledge
    if user_text:
        rag_results = rag_retrieve(user_text, k=2)
        if rag_results:
            kb_text = "\n".join([f"Q: {r.get('q')}\nA: {r.get('a')}" for r in rag_results if r.get('a')])
            if kb_text:
                messages_for_openai.append({
                    "role": "system",
                    "content": f"Voici des réponses de la base de connaissance qui peuvent t'aider:\n{kb_text}"
                })

    # Add conversation history
    messages_for_openai += [{"role": m.role, "content": m.content} for m in req.messages]

    # Call OpenAI
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages_for_openai,
            temperature=0.3,
        )
        reply = resp.choices[0].message.content or "Désolé, pas de réponse."
        return ChatResponse(
            reply=reply,
            session_id=sid,
            lang=lang
        )
    except Exception as e:
        return ChatResponse(
            reply=f"[ERROR] Server error: {str(e)}",
            session_id=sid,
            lang=lang
        )

if __name__ == "__main__":
    import uvicorn
    print("[*] Starting server...")
    load_rag_csv()
    print("[OK] RAG index loaded")
    uvicorn.run(app, host="127.0.0.1", port=8000)
