from dotenv import load_dotenv
load_dotenv()

print("[DEBUG] Imports starting...")

from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os
from openai import OpenAI
import uuid
from typing import Optional

print("[DEBUG] Base imports done, loading RAG...")

# Import RAG and language detection modules
from rag import load_rag_csv, rag_retrieve
from language_detection import normalize_lang, llm_detect_language

print("[DEBUG] All imports successful")

app = FastAPI(title="TLX Backend - Chat Only")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# Health endpoint
@app.get("/health")
async def health():
    return {"status": "ok"}

# Chat endpoint - MINIMAL VERSION
@app.post("/chat", response_model=ChatResponse)
async def chat(
    messages: str = Form(...),
    session_id: str | None = Form(None),
    language: str | None = Form(None),
):
    """Minimal chat endpoint for testing."""
    print(f"[DEBUG] /chat called")
    try:
        if not messages:
            return ChatResponse(
                reply="No messages provided",
                session_id=session_id or str(uuid.uuid4()),
                lang="fr"
            )
        
        print(f"[DEBUG] Parsing JSON: {messages[:50]}...")
        parsed = json.loads(messages)
        print(f"[DEBUG] Parsed {len(parsed)} messages")
        req = ChatRequest(
            messages=[Message(**m) for m in parsed],
            session_id=session_id,
        )
        print(f"[DEBUG] ChatRequest created")
    except Exception as e:
        print(f"[ERROR] Parse error: {str(e)}")
        import traceback
        traceback.print_exc()
        return ChatResponse(
            reply=f"Parse error: {str(e)}",
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

    # Build messages for OpenAI with RAG knowledge
    messages_for_openai = []

    # Language policy
    lang_name = {"fr": "Francais", "en": "English", "ar": "Arabic"}.get(lang, "Francais")
    messages_for_openai.append({
        "role": "system",
        "content": f"You are a helpful assistant. Reply ONLY in {lang_name}. Be concise and friendly."
    })

    # Add RAG knowledge
    if user_text:
        rag_results = rag_retrieve(user_text, k=2)
        if rag_results:
            kb_text = "\n".join([f"Q: {r.get('q')}\nA: {r.get('a')}" for r in rag_results if r.get('a')])
            if kb_text:
                messages_for_openai.append({
                    "role": "system",
                    "content": f"Knowledge base results:\n{kb_text}"
                })

    # Add conversation history
    messages_for_openai += [{"role": m.role, "content": m.content} for m in req.messages]

    # Call OpenAI
    try:
        print(f"[DEBUG] Calling OpenAI with {len(messages_for_openai)} messages")
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages_for_openai,
            temperature=0.3,
        )
        reply = resp.choices[0].message.content or "Sorry, no response."
        print(f"[DEBUG] Got response: {reply[:50]}...")
        return ChatResponse(
            reply=reply,
            session_id=sid,
            lang=lang
        )
    except Exception as e:
        print(f"[ERROR] OpenAI call failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return ChatResponse(
            reply=f"OpenAI error: {str(e)}",
            session_id=sid,
            lang=lang
        )

if __name__ == "__main__":
    import uvicorn
    print("[*] Starting server...")
    load_rag_csv()
    print("[OK] RAG index loaded")
    uvicorn.run(app, host="127.0.0.1", port=8000)
