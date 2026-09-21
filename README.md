---
title: StudentAI Platform
emoji: 🤖
colorFrom: blue
title: StudentAI Platform
colorTo: purple
sdk: docker
app_file: Dockerfile
pinned: false
---

# StudentAI Platform — Agentic Database System

Full-stack agentic AI platform for student database management.
Natural language → FastAPI → SQLite → Claude → UI.

---

## Stack

| Layer    | Tech                          |
|----------|-------------------------------|
| Backend  | Python 3.11 · FastAPI · SQLAlchemy · SQLite |
| AI Agent | Anthropic Claude (claude-sonnet-4) |
| Frontend | Vanilla HTML · CSS · JavaScript (no framework) |
| DB       | SQLite (file: `students.db`)  |

---

## Project Structure

```
student_ai_platform/
├── backend/
│   ├── main.py          ← FastAPI app + /api/agent endpoint + voice router
│   ├── database.py      ← SQLAlchemy engine & session (sync, students.db)
│   ├── models.py        ← ORM: Student, Course, Enrollment
│   ├── schemas.py       ← Pydantic schemas
│   ├── crud.py          ← All DB operations + analytics
│   ├── seed.py          ← 15 students · 10 courses · 24 enrollments
│   ├── data/            ← RAG knowledge base source docs (PDF/DOCX/TXT)
│   ├── voice/           ← Voice Assistant module (see below)
│   │   ├── database.py  ← separate ASYNC engine (voice.db) — kept isolated
│   │   ├── models.py    ← Conversation / Message / Document
│   │   ├── crud.py
│   │   ├── security.py  ← optional admin gate + rate limiting
│   │   ├── session.py   ← in-memory per-session chat history
│   │   ├── router.py    ← /api/voice/* endpoints
│   │   └── services/
│   │       ├── rag/     ← FAISS + sentence-transformers
│   │       ├── stt/     ← faster-whisper + language detection
│   │       ├── tts/     ← edge-tts
│   │       ├── llm/     ← Gemini
│   │       └── emotion/ ← keyword / optional HF emotion detection
│   ├── .env             ← both GROQ_API_KEY and GEMINI_API_KEY live here
│   └── requirements.txt
├── frontend/
│   ├── index.html       ← includes the new "Voice Assistant" nav tab
│   └── static/
│       ├── css/style.css
│       └── js/app.js
└── README.md
```

---

## Voice Assistant (new)

Ported from a separate AI-Phone-Agent project's browser-voice pipeline —
Twilio/phone calling was **not** included, only the browser voice chat,
speech-to-text, text-to-speech, and RAG document Q&A pieces.

- **Nav tab:** "Voice Assistant" — hold the mic button, speak, release; or type instead.
- **How it works:** one round trip to `POST /api/voice/converse` runs
  STT (faster-whisper) → RAG lookup (FAISS) → Gemini → TTS (edge-tts) and
  returns the transcript, the answer text, and the answer as spoken audio.
- **Knowledge base:** drop PDFs/DOCX/TXT into `backend/data/` before
  first run, or use the "Upload document to knowledge base" button in
  the Voice Assistant panel at any time — it's the same FAISS index
  either way.
- **Its own database:** conversations/messages are stored in a separate
  `voice.db` (async SQLAlchemy) so nothing touches the existing sync
  `students.db` / Student-Course-Enrollment schema.
- **Config:** set `GEMINI_API_KEY` in `backend/.env` (the agent won't
  respond without it). `AGENT_NAME` / `AGENT_INSTITUTION` control how
  it introduces itself; `WHISPER_MODEL_SIZE` trades speed for accuracy.
  See `backend/.env` for the full list, all pre-filled with sensible
  defaults.
- **Mic access:** browsers only allow microphone access on `localhost`
  or HTTPS — `http://localhost:8000` works out of the box; a real
  deployment needs TLS.
- **Not included (by design):** Twilio phone calling, real-time
  streaming voice-activity-detection audio (this uses push-to-talk
  instead), call analytics/lead-capture dashboards. The `voice/`
  package is a plain subpackage, so any of that can be added later
  without touching the rest of the app.

---

## Setup & Run

```bash
# 1. Go to backend
cd student_ai_platform/backend

# 2. Create virtual env
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# 3. Install deps
pip install -r requirements.txt

# 4. Set API keys — edit backend/.env (already created), fill in:
#      GROQ_API_KEY=...     (existing AI Agent tab)
#      GEMINI_API_KEY=...   (new Voice Assistant tab)

# 5. Run
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** — done.

---

## API Reference

| Method | Endpoint                      | Description           |
|--------|-------------------------------|-----------------------|
| GET    | /api/students                 | List / filter students|
| GET    | /api/students/{id}            | Get one student       |
| POST   | /api/students                 | Create student        |
| PUT    | /api/students/{id}            | Update student        |
| DELETE | /api/students/{id}            | Delete student        |
| GET    | /api/courses                  | List courses          |
| GET    | /api/enrollments/{id}         | Student enrollments   |
| GET    | /api/analytics/summary        | Key metrics           |
| GET    | /api/analytics/department     | Dept stats            |
| GET    | /api/analytics/at-risk        | At-risk students      |
| GET    | /api/analytics/ranking        | GPA leaderboard       |
| GET    | /api/students/{id}/report     | Full student report   |
| POST   | /api/agent                    | **AI agent**          |
| POST   | /api/voice/converse            | Voice: audio in → transcript + reply + speech out |
| POST   | /api/voice/chat                | Voice: typed query → reply (no audio)   |
| POST   | /api/voice/stt                 | Speech-to-text only    |
| POST   | /api/voice/tts                 | Text-to-speech only    |
| POST   | /api/voice/upload-doc          | Add a document to the RAG knowledge base |
| GET    | /api/voice/docs-status         | RAG index stats        |
| GET    | /api/voice/conversations       | List voice conversations |
| GET    | /api/voice/conversations/{id}  | One conversation's messages |
| DELETE | /api/voice/sessions/{id}       | Clear a live session    |

Swagger UI: http://localhost:8000/docs

---

## 10 Agentic Capabilities

1. **Query** — "Show all CS students with GPA above 3.5"
2. **Insert** — "Add student: Ravi Kumar, 21, CS, GPA 3.8, ravi@uni.edu"
3. **Update** — "Update GPA of student ID 3 to 3.9"
4. **Delete** — "Delete student with ID 12"
5. **Analytics** — "Average GPA by department"
6. **Risk Detection** — "Who is at risk of academic failure?"
7. **Schema Info** — "Describe the database tables"
8. **Reports** — "Full report for student ID 1"
9. **Ranking** — "Rank all students by GPA"
10. **SQL Assistant** — "Write SQL to find top 3 per department"

---

## Database Schema

```sql
students    (id, name, age, department, gpa, email, enrollment_year, status)
courses     (id, name, department, credits)
enrollments (id, student_id, course_id, grade, semester)
```
