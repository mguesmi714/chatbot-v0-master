# Chatbot V0 — Next.js + FastAPI (Agent IA)

Prototype de chatbot **full-stack** :
- **Frontend** : Next.js (React + TypeScript + Tailwind)
- **Backend** : FastAPI (Python) + Agent IA (OpenAI)
- (Bientôt) RAG : LlamaIndex + Qdrant
- (Bientôt) Mémoire : Redis / Postgres
- (Bientôt) Actions : Make / APIs internes.

---

## 🗂️ Structure du projet

```
chatbot-v0/
  frontend/          # UI Chat (Next.js)
  backend/           # API + agent IA (FastAPI)
  README.md
  .gitignore
```

---

## 📚 Guide de lecture du repo (ce qui a été fait)

Cette section documente précisément les points clés du repo pour que vous puissiez lire et comprendre rapidement le code modifié.

### 1) Multilingue intelligent (FR/EN/AR)

- Détection automatique de la langue via LLM côté backend (fr | en | ar), avec repli simple si nécessaire.
  - Implémentation: [backend/main.py](backend/main.py)
  - Fonctions clés:
    - `normalize_lang()` / `detect_language()` pour la normalisation et repli simple
    - `llm_detect_language(text)` pour la détection par modèle
    - Dictionnaires `I18N` et `LANG_NAMES` pour les messages localisés
- Réponses du bot toujours dans la langue choisie/détectée
  - Une consigne “system” est ajoutée aux messages OpenAI pour forcer la langue et ne pas traduire les données sensibles (noms, numéros, dates)
- Sélection manuelle possible via le frontend (select FR/EN/AR) ou en envoyant un message `FR`/`EN`/`AR`.

Frontend (UI localisée + RTL arabe):
- Sélecteur de langue, greeting, labels, boutons, placeholders, titres des pièces jointes localisés
- Passage RTL automatique pour l’arabe
- Fichier: [frontend/app/page.tsx](frontend/app/page.tsx)
- Composant pièces jointes internationalisé: [frontend/components/FileSlot.tsx](frontend/components/FileSlot.tsx)

### 2) Comment le frontend appelle le backend

- URL: `POST http://127.0.0.1:8000/chat`
- Corps: `multipart/form-data` avec:
  - `messages`: string JSON (tableau de `{ role, content }`)
  - `session_id`: string (stocké dans localStorage)
  - `language`: string optionnel (`fr` | `en` | `ar`) pour forcer la session
  - `prescription_file`, `insurance_file`: fichiers optionnels (PDF / image)
- Implémentation côté UI: [frontend/app/page.tsx](frontend/app/page.tsx)

### 2.1) RAG Q/R (FAQ csv) — comment ça marche

Objectif: permettre au bot de répondre à partir d’un fichier CSV de questions/réponses (FAQ interne), en FR/EN/AR.

Chargement & nettoyage
- Placez votre fichier source dans `backend/QR.csv` (par défaut) ou définissez `RAG_CSV_PATH` dans `backend/.env`.
- Le parseur détecte encodage (UTF‑8 → CP1252 en repli) et délimiteur (priorité `;`, sinon `,`).
- Les colonnes Q/R sont détectées par l’en‑tête (`question|quest` et `réponse|repon|answer`). Si absent, on prend les 2 dernières cellules non vides de chaque ligne.
- Endpoint de nettoyage: `POST /rag/clean` → génère `backend/QR_clean.csv` en UTF‑8 avec 2 colonnes standard `question,answer` et recharge l’index.
- Démarrage: le serveur charge `RAG_CSV_PATH` s’il est lisible; sinon il essaie automatiquement `QR_clean.csv`.

Endpoints RAG
- `GET /rag/status` → `{ count, config_path, loaded_path }`
- `POST /rag/clean` → nettoie `QR.csv` en `QR_clean.csv` + recharge; renvoie `{ ok, src, dst, count, reloaded }`
- `POST /rag/reload` → recharge l’index (facultatif, avec `?path=...`)
- `POST /rag/ask` → répond uniquement depuis le CSV. Form-data: `q` (question), `language` (optionnel: `fr|en|ar`). Retour: `{ answer, matched_question, lang }`
- `GET /rag/debug?q=...` → debug: montre les meilleurs matchs lexicaux (scores + Q/A)

Stratégie de recherche (retrieval)
- Chemin rapide (exact/proche): si la question de l’utilisateur correspond de très près à une Q du CSV, on renvoie directement la réponse du CSV (sans appeler le LLM). Similarité lexicale normalisée (accents retirés), seuil ≈ 0.85 + boost sur sous‑chaîne/exact.
- Sinon: récupération hybride
  - Embeddings calculés à la demande (pas au démarrage) pour question et documents;
  - Repli lexical rapide si l’API d’embeddings n’est pas disponible.
- Les meilleurs extraits (Q/A) sont ensuite injectés dans le contexte du LLM si besoin.

Langue des réponses
- La langue de réponse est strictement celle de la session (FR/EN/AR). Si la réponse CSV est en FR et la session en EN/AR, elle est traduite automatiquement avant affichage (noms/numéros/dates non traduits).

Variables d’env utiles (backend/.env)
```
RAG_CSV_PATH=QR.csv           # ou QR_clean.csv si vous voulez forcer le fichier nettoyé
OPENAI_EMBED_MODEL=text-embedding-3-small
RAG_USE_EMBED=false           # par défaut: retrieval lexical sans embeddings
RAG_TRANSLATE=false           # traduire la réponse CSV vers la langue cible (si true)
LANG_USE_LLM=false            # activer la détection de langue par LLM (sinon heuristique rapide)
```

Bonnes pratiques CSV
- Une question courte et claire; une réponse concise.
- Évitez les sauts de ligne dans les cellules; si besoin, utilisez le nettoyage pour standardiser.
- Si votre source comporte beaucoup de colonnes, assurez‑vous que les deux dernières non vides sont bien (Q, A) ou nommez les colonnes « Question » et « Réponse ».

### 3) Endpoints FastAPI

- `GET /health` → simple statut
- `POST /chat` → logique principale du chatbot (flow location + fallback IA)
  - Paramètres `Form`: `messages`, `session_id`, `language`
  - Paramètres `File`: `prescription_file`, `insurance_file`
  - Réponse: `{ reply: string, session_id: string }`
- `GET /lang/detect?text=...` → helper dev: renvoie `{ language: fr|en|ar }`
- `POST /rag/ask` → répond depuis la base CSV (voir 2.1)
- `GET /rag/debug` → diagnostic matching (voir 2.1)
- CORS: autorise http://localhost:3000
- Implémentation: [backend/main.py](backend/main.py)

### 3.1) Mode “Question/Aide” (UI)

- Dans l’UI, un bouton “Question/Aide” est disponible à deux endroits:
  - Dans les actions rapides (à côté de Bonjour/Location/Ordonnance)
  - Dans l’entête du slot “Ordonnance” (quand la section PJ est visible)
- Comportement:
  1. Au clic, le bot affiche un prompt localisé (FR/EN/AR): “Comment puis-je vous aider ? …”
  2. Les messages suivants sont routés vers `POST /rag/ask` et répondus uniquement depuis la base CSV (RAG). Pas d’appel LLM.
  3. Le mode se désactive si vous lancez la “Location” ou si vous faites “Réinitialiser”.
- La langue UI est envoyée à `/rag/ask` pour obtenir une réponse traduite si `RAG_TRANSLATE=true`.

### 4) Sessions et mémoire en RAM

- Dictionnaire en mémoire `SESSIONS` indexé par `session_id`
- Contenu par session:
  - `lang`: langue choisie/détectée
  - `step`: étape du flow (`ASK_RENTAL_ALL` → `CONFIRM_RENTAL`)
  - `data`: infos client + métadonnées pièces jointes (base64, filename, content_type)
  - `raw_intake`, `created_at`
- Implémentation: [backend/main.py](backend/main.py)

### 5) Gestion des pièces jointes

- Types autorisés: PDF, JPG, PNG, WebP (max 6 Mo)
- Backend: lecture, validation, encodage base64, stockage dans `SESSIONS[sid]['data']`
- Frontend: composant `FileSlot` localisé, affichage automatique de la zone PJ quand le bot la demande (FR/EN/AR)
- Implémentations:
  - Backend: [backend/main.py](backend/main.py)
  - Frontend: [frontend/app/page.tsx](frontend/app/page.tsx), [frontend/components/FileSlot.tsx](frontend/components/FileSlot.tsx)

### 6) Flow “Location de tire-lait”

- Déclencheurs multilingues (FR/EN/AR) détectés dans le message utilisateur
- Étapes:
  1. Demande d’info en un seul message + 2 PJ
  2. Vérification automatique (LLM) + corrections éventuelles
  3. Récapitulatif localisé + confirmation “OUI/YES/نعم”
  4. Envoi webhook (si `MAKE_WEBHOOK_URL` configurée)
- Implémentation: [backend/main.py](backend/main.py)

---

## ⚙️ Configuration & Variables d’environnement

Backend: `backend/.env`

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
MAKE_WEBHOOK_URL=   # optionnel
PROMPT_RELOAD=false # optionnel (1/true pour recharger le prompt system.md à chaud)
# RAG / Langues
RAG_CSV_PATH=QR.csv        # ou QR_clean.csv
RAG_USE_EMBED=false        # retrieval lexical par défaut
RAG_TRANSLATE=false        # traduire la réponse CSV vers la langue UI
LANG_USE_LLM=false         # detection LLM optionnelle (sinon heuristique)
```

Frontend: pas de .env requis pour la V0. Le sélecteur de langue persiste `tlx_lang` et la session `tlx_session_id` en localStorage.

---

## ▶️ Démarrage rapide

1) Backend

```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

2) Frontend

```
cd frontend
npm install
npm run dev
```

3) Ouvrir http://localhost:3000

- Écrire en arabe/anglais/français → le bot répond dans la langue détectée.
- Changer la langue via le sélecteur → l’UI et les réponses basculent.
- Taper “location”/“rental”/“استئجار” → le flow location démarre (FR/EN/AR).

---

## ✅ Prérequis

- Node.js (LTS recommandé)
- Python 3.11+
- Git
- (Optionnel) Docker Desktop — pour Qdrant/Redis/Postgres plus tard

Vérifier l’installation :

```bash
node -v
npm -v
python --version
git --version
```

---

## 🚀 Lancer le projet en local

⚠️ Ouvre **2 terminaux** : un pour le backend, un pour le frontend.

---

## 1️⃣ Backend (FastAPI)

Aller dans le backend :

```bash
cd backend
```

Créer et activer l’environnement virtuel (Windows) :

```bash
python -m venv .venv
.venv\Scripts\activate
```

Installer les dépendances :

```bash
pip install -r requirements.txt
```

Configurer les variables d’environnement :

```bash
copy .env.example .env
```

Puis éditer `backend/.env` :

```env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_MODEL=gpt-4o-mini
```

Lancer le serveur :

```bash
uvicorn main:app --reload --port 8000
```

✅ Swagger : http://127.0.0.1:8000/docs  
✅ Healthcheck : http://127.0.0.1:8000/health  

---

## 2️⃣ Frontend (Next.js)

Aller dans le frontend :

```bash
cd ../frontend
```

Installer les dépendances :

```bash
npm install
```

Lancer l’app :

```bash
npm run dev
```

✅ UI : http://localhost:3000  

---

## 🔌 API utilisée par le frontend

Le frontend appelle le backend sur :

- `POST http://127.0.0.1:8000/chat`

Format de requête :

```json
{
  "messages": [
    { "role": "user", "content": "Bonjour" }
  ]
}
```

Format de réponse :

```json
{
  "reply": "Bonjour ! Comment puis-je vous aider ?"
}
```

---

## 🧪 Test manuel rapide

1) Lance backend + frontend  
2) Va sur http://localhost:3000  
3) Tape :
- Bonjour
- Je veux louer un tire-lait
- Mon code postal est 75011

---

## 🔐 Sécurité (IMPORTANT)

✅ Ne jamais commiter de secrets (clé OpenAI).

Le fichier `backend/.env` est ignoré via `.gitignore`.

Les collègues doivent utiliser :
- `backend/.env.example` → à copier en `.env`

---

## 🤝 Collaboration Git (recommandé)

Branches :
- `main` : stable
- `feature/*` : nouvelles features
- `fix/*` : corrections

Créer une branche :

```bash
git checkout -b feature/nom-de-feature
```

Commit & push :

```bash
git add .
git commit -m "Describe your change"
git push -u origin feature/nom-de-feature
```

Ensuite ouvrir une **Pull Request** sur GitHub.

---

## 🛠️ Troubleshooting

### ❌ Erreur "Failed to fetch" depuis le frontend
✅ Vérifie que FastAPI tourne : http://127.0.0.1:8000/docs  
✅ Vérifie que CORS autorise http://localhost:3000 (CORSMiddleware dans `main.py`).

### ❌ Port déjà utilisé
```bash
uvicorn main:app --reload --port 8001
```
Et change l’URL dans le frontend.

### ❌ Imports Python en rouge dans IntelliJ
### ❌ Multilingue ne bascule pas
- Vérifiez `/lang/detect?text=...` avec vos phrases (FR/EN/AR)
- Si vos phrases en français basculent en “en”, rajoutez des mots FR (ex: “bonjour”) ou forcez la langue via le sélecteur UI. Vous pouvez activer `LANG_USE_LLM=true` si nécessaire.

### ❌ “Question/Aide” ne trouve pas de réponse
- Ouvrez `/rag/debug?q=...` pour voir les meilleurs matchs et vérifier la colonne “answer”.
- Nettoyez/rechargez: `POST /rag/clean` ou `POST /rag/reload`.

---

## 🗓️ Changelog – 2026-02-02

Backend
- Chargement RAG fiabilisé: embeddings à la demande (optionnels), retrieval lexical robuste; fallback auto vers `QR_clean.csv` au démarrage.
- Parsing CSV tolérant encodage/délimiteur + détection colonnes Q/R; endpoint `POST /rag/clean` pour produire `QR_clean.csv` UTF‑8 (2 colonnes).
- Endpoints RAG:
  - `GET /rag/status` → ajoute `config_path` et `loaded_path`
  - `POST /rag/reload` / `POST /rag/clean`
  - `POST /rag/ask` (Form: `q`, `language`) → réponse uniquement depuis CSV
  - `GET /rag/debug` → diagnostic lexical (top scores + Q/A)
- Multilingue: heuristique renforcée (FR/EN/AR) + LLM optionnel (`LANG_USE_LLM`).
- Traduction optionnelle des réponses CSV vers la langue cible (`RAG_TRANSLATE`).
- Hook FastAPI `startup` pour charger l’index sans erreur d’ordre d’import.

Frontend
- Ajout du mode “Question/Aide”:
  - Bouton dans les actions rapides et à côté d’“Ordonnance”.
  - Prompt “Comment puis-je vous aider ?” puis réponses via `/rag/ask` (CSV only).
  - Sortie du mode à la “Location” ou “Réinitialiser”.
- Envoi de la langue UI vers `/rag/ask` pour répondre dans la langue choisie.
- Bouton “Question/Aide” cliquable même sans texte saisi.

Variables d’env (nouveaux)
- `RAG_USE_EMBED`, `RAG_TRANSLATE`, `LANG_USE_LLM`, `RAG_CSV_PATH`.

Tests rapides
- `GET /rag/status` → `count > 0`, `loaded_path` défini
- `POST /rag/ask` (Form: q=“mon TL ne fonctionne plus”) → réponse CSV
- UI: cliquer “Question/Aide” → poser “le tl ne fonctionne pas” → réponse trouvée
Configurer l’interpréteur :
- `backend\.venv\Scripts\python.exe`

---

## 🧭 Roadmap

### ✅ V0
- [x] UI Next.js
- [x] Backend FastAPI
- [x] Endpoint `/chat`
- [x] IA via OpenAI (gpt-4o-mini)
- [x] Multilingue intelligent (FR/EN/AR) — détection LLM + UI localisée

### 🔜 V1
- [ ] Sessions + mémoire (Redis/Postgres)
- [ ] Streaming réponses
- [ ] Analytics (logs)

### 🔜 V2
- [ ] RAG : LlamaIndex + Qdrant
- [ ] Ingestion docs + retrieval
- [ ] Réponses sourcées

### 🔜 V3
- [ ] Actions (Make / APIs internes)
- [ ] Monitoring (Metabase + dashboard)
