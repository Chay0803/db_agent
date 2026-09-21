import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from groq import Groq
from dotenv import load_dotenv
import json
import re

from database import engine, get_db, Base
from models import Student, Course, Enrollment
from schemas import (
    StudentCreate, StudentUpdate, StudentResponse,
    CourseResponse, EnrollmentResponse, AgentRequest, AgentResponse,
)
from seed import seed_database
import crud

# ── Voice module (browser voice chat: STT / RAG / Gemini / TTS) ───────────────
from voice.database import init_db as voice_init_db
from voice.router import router as voice_router
from voice.services.rag.retriever import ingest_folder as voice_ingest_folder, warmup as voice_rag_warmup
from voice.services.stt.transcriber import warmup as voice_stt_warmup

load_dotenv()

# ── App ───────────────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Student platform seed data (sync engine — unchanged from before)
    db = next(get_db())
    seed_database(db)

    # Voice module startup: its own async DB tables, RAG document ingestion,
    # and warming the STT/embedding models so the first real request is fast.
    await voice_init_db()
    data_dir = os.getenv("VOICE_DATA_DIR", "data")
    try:
        voice_ingest_folder(data_dir)
    except Exception as e:
        print(f"[voice] document ingestion skipped: {e}")

    warmups = []
    if os.getenv("WARMUP_STT", "true").lower() == "true":
        warmups.append(voice_stt_warmup())
    if os.getenv("WARMUP_RAG", "true").lower() == "true":
        warmups.append(voice_rag_warmup())
    if warmups:
        await asyncio.gather(*warmups, return_exceptions=True)

    yield


app = FastAPI(title="Student AI Platform", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice_router)

# Serve frontend static files
frontend_path = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_path / "static")), name="static")

@app.get("/")
def root():
    return FileResponse(str(frontend_path / "index.html"))


# ── Student endpoints ─────────────────────────────────────────────────────────

@app.get("/api/students", response_model=list[StudentResponse])
def list_students(
    department: Optional[str] = None,
    min_gpa:    Optional[float] = None,
    max_gpa:    Optional[float] = None,
    status:     Optional[str] = None,
    db: Session = Depends(get_db),
):
    return crud.get_students(db, department, min_gpa, max_gpa, status)


@app.get("/api/students/{student_id}", response_model=StudentResponse)
def get_student(student_id: int, db: Session = Depends(get_db)):
    s = crud.get_student(db, student_id)
    if not s:
        raise HTTPException(404, "Student not found")
    return s


@app.post("/api/students", response_model=StudentResponse, status_code=201)
def create_student(data: StudentCreate, db: Session = Depends(get_db)):
    return crud.create_student(db, data)


@app.put("/api/students/{student_id}", response_model=StudentResponse)
def update_student(student_id: int, data: StudentUpdate, db: Session = Depends(get_db)):
    s = crud.update_student(db, student_id, data)
    if not s:
        raise HTTPException(404, "Student not found")
    return s


@app.delete("/api/students/{student_id}")
def delete_student(student_id: int, db: Session = Depends(get_db)):
    ok = crud.delete_student(db, student_id)
    if not ok:
        raise HTTPException(404, "Student not found")
    return {"message": f"Student {student_id} deleted"}


# ── Course & Enrollment endpoints ─────────────────────────────────────────────

@app.get("/api/courses", response_model=list[CourseResponse])
def list_courses(db: Session = Depends(get_db)):
    return crud.get_courses(db)


@app.put("/api/courses/{course_id}")
def update_course(course_id: int, data: dict, db: Session = Depends(get_db)):
    c = crud.update_course(db, course_id, data)
    if not c:
        raise HTTPException(404, "Course not found")
    return c


@app.get("/api/enrollments/{student_id}", response_model=list[EnrollmentResponse])
def get_enrollments(student_id: int, db: Session = Depends(get_db)):
    return crud.get_enrollments(db, student_id)


# ── Analytics endpoints ───────────────────────────────────────────────────────

@app.get("/api/analytics/summary")
def analytics_summary(db: Session = Depends(get_db)):
    return crud.get_summary_analytics(db)


@app.get("/api/analytics/department")
def analytics_department(db: Session = Depends(get_db)):
    return crud.get_department_analytics(db)


@app.get("/api/analytics/at-risk")
def analytics_at_risk(db: Session = Depends(get_db)):
    return crud.get_at_risk_students(db)


@app.get("/api/analytics/ranking")
def analytics_ranking(db: Session = Depends(get_db)):
    return crud.get_student_ranking(db)


@app.get("/api/students/{student_id}/report")
def student_report(student_id: int, db: Session = Depends(get_db)):
    r = crud.get_student_report(db, student_id)
    if not r:
        raise HTTPException(404, "Student not found")
    return r


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_students_table(students) -> str:
    """Render a list of Student ORM objects as a markdown table."""
    if not students:
        return "_No students match the given criteria._"
    rows = ["| ID | Name | Department | GPA | Status |",
            "|----|------|------------|-----|--------|"]
    for s in students:
        rows.append(f"| {s.id} | {s.name} | {s.department} | {s.gpa} | {s.status} |")
    return "\n".join(rows)


def student_chart_data(students, request_text):
    """Build a chart only when the request calls for a visual comparison."""
    if len(students) < 2:
        return None

    request = request_text.lower()
    visual_terms = (
        "chart", "graph", "visual", "dashboard", "compare", "comparison",
        "distribution", "breakdown", "trend", "average", "how many",
        "per department", "by department", "top ", "rank",
    )
    if not any(term in request for term in visual_terms):
        return None

    if "status" in request or "probation" in request or "at-risk" in request:
        counts = {}
        for student in students:
            counts[student.status] = counts.get(student.status, 0) + 1
        return {
            "type": "count_by_status",
            "title": "Student status breakdown",
            "labels": list(counts),
            "values": list(counts.values()),
        }

    if "department" in request:
        groups = {}
        for student in students:
            groups.setdefault(student.department, []).append(student.gpa)
        return {
            "type": "gpa_by_department",
            "title": "Average GPA by department",
            "labels": list(groups),
            "values": [round(sum(gpas) / len(gpas), 2) for gpas in groups.values()],
        }

    return {
        "type": "gpa_by_student",
        "title": "GPA by student",
        "labels": [student.name for student in students],
        "values": [student.gpa for student in students],
    }


# ── AI Agent endpoint ─────────────────────────────────────────────────────────

@app.post("/api/agent", response_model=AgentResponse)
def agent_query(req: AgentRequest, db: Session = Depends(get_db)):

    # ── Build lightweight schema context (no raw data rows) ──────────────────
    # Sending every row into the prompt causes the model to hallucinate values.
    # Instead we give the model schema + aggregate stats, and let it emit a
    # structured `query` action that the backend resolves against the real DB.
    summary    = crud.get_summary_analytics(db)
    dept_stats = crud.get_department_analytics(db)
    courses    = crud.get_courses(db)

    schema_context = {
        "tables": {
            "students": {
                "columns": ["id", "name", "age", "department", "gpa",
                            "email", "enrollment_year", "status"],
                "status_values": ["active", "probation", "graduated"],
                "departments": list({r["department"] for r in dept_stats}),
            },
            "courses": {
                "columns": ["id", "name", "department", "credits"],
                "all_courses": [{"id": c.id, "name": c.name, "credits": c.credits} for c in courses],
            },
            "enrollments": {
                "columns": ["id", "student_id", "course_id", "grade", "semester"],
            },
        },
        "summary_stats": summary,
        "department_stats": dept_stats,
    }

    system_prompt = f"""You are an intelligent AI agent for a Student Database Management System.

Database schema and aggregate statistics (do NOT invent individual student data):
{json.dumps(schema_context, indent=2)}

IMPORTANT — Accuracy rules:
- You do NOT have individual student rows in your context.
- For any query/search/filter request you MUST emit a `query` action so the backend fetches real data.
- For UPDATE/DELETE by name (not ID), emit `find_and_update` or `find_and_delete` — the backend will search by name and apply the change automatically. No confirmation needed.
- Only use summary_stats and department_stats for high-level analytics answers.
- Always confirm what action was taken or will be taken.

You can perform ALL of these operations:
1. QUERY/SEARCH — Filter students by any field → emit a `query` action
2. INSERT — Add a new student → emit an `insert` action
3. UPDATE by ID — Modify a student when you have their ID → emit an `update` action
4. UPDATE by name — Modify a student referred to by name → emit a `find_and_update` action
5. DELETE by ID — Remove a student when you have their ID → emit a `delete` action
6. DELETE by name — Remove a student referred to by name → emit a `find_and_delete` action
7. ANALYTICS — Use summary_stats / department_stats already in context
8. RISK DETECTION — Emit a `query` action with max_gpa=2.0 or status=probation
9. SCHEMA INFO — Describe tables and relationships from schema above
10. REPORTS — Emit a `report` action with the student_id
11. RANKING — Emit a `ranking` action
12. SQL ASSISTANT — Write valid SQLite queries; do not execute them

Append ONE action block at the END of your response when needed:

QUERY (filter students — backend will return real rows):
```action
{{"operation":"query","filters":{{"department":null,"min_gpa":null,"max_gpa":2.0,"status":null}},"description":"Students with GPA below 2.0"}}
```

INSERT:
```action
{{"operation":"insert","data":{{"name":"...","age":0,"department":"...","gpa":0.0,"email":"...","enrollment_year":2024,"status":"active"}}}}
```

UPDATE by ID (use when you already know the student_id):
```action
{{"operation":"update","student_id":1,"data":{{"gpa":3.9}}}}
```

UPDATE by name (use when user refers to student by name — backend resolves ID automatically):
```action
{{"operation":"find_and_update","name":"Aisha Patel","data":{{"gpa":3.9}}}}
```

DELETE by ID:
```action
{{"operation":"delete","student_id":1}}
```

DELETE by name (use when user refers to student by name):
```action
{{"operation":"find_and_delete","name":"Vikram Rao"}}
```

REPORT (full profile for one student):
```action
{{"operation":"report","student_id":1}}
```

RANKING (sorted by GPA):
```action
{{"operation":"ranking"}}
```

UPDATE COURSE by name (use when user wants to change course credits, name, or department):
```action
{{"operation":"update_course","name":"Operating Systems","data":{{"credits":4}}}}
```

Rules:
- Be extremely concise. One sentence max before showing data.
- NEVER explain what you are about to do, what action you will emit, or describe filter parameters — just do it.
- NEVER write section headers like "## Query Action", "## Explanation", "## Additional Insight". No markdown headers at all.
- For queries: write nothing before the action block — the backend injects the real table. You may add one short insight sentence AFTER if genuinely useful.
- For writes (insert/update/delete): one confirmation line only, e.g. "Updated Aisha Patel's GPA to 3.9."
- For analytics questions answered from context: answer directly in 1-3 sentences or a short table, no preamble.
- ALWAYS execute write operations immediately without asking for confirmation.
- NEVER fabricate individual student names, GPAs, or IDs — always use a query action.
- SQL: show the query in a code block only, no extra explanation unless asked.
"""

    # ── Groq API call ────────────────────────────────────────────────────────
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(500, "GROQ_API_KEY not set in environment / .env file")

    client = Groq()
    completion = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": req.message},
        ],
        temperature=0.3,          # lower = more faithful, less hallucination
        max_tokens=1024,
        top_p=1,
        stream=False,
        stop=None,
    )
    ai_text = completion.choices[0].message.content or ""
    db_action_taken = None

    # ── Parse & execute action block ─────────────────────────────────────────
    action_match = re.search(r"```action\s*([\s\S]*?)```", ai_text)
    injected_table = ""   # real DB data to splice into the response

    if action_match:
        try:
            action = json.loads(action_match.group(1).strip())
            op = action.get("operation")

            # ── QUERY: run real DB filter, inject markdown table ─────────────
            if op == "query":
                f = action.get("filters", {})
                results = crud.get_students(
                    db,
                    department=f.get("department"),
                    min_gpa=f.get("min_gpa"),
                    max_gpa=f.get("max_gpa"),
                    status=f.get("status"),
                )
                injected_table = format_students_table(results)
                db_action_taken = {
                    "operation": "query",
                    "filters": f,
                    "count": len(results),
                }
                visualization = student_chart_data(results, req.message)
                if visualization:
                    db_action_taken["visualization"] = visualization

            # ── RANKING: return sorted list from DB ──────────────────────────
            elif op == "ranking":
                ranking = crud.get_student_ranking(db)
                rows = ["| Rank | ID | Name | Department | GPA |",
                        "|------|----|----- |------------|-----|"]
                for r in ranking:
                    rows.append(
                        f"| {r['rank']} | {r['id']} | {r['name']} "
                        f"| {r['department']} | {r['gpa']} |"
                    )
                injected_table = "\n".join(rows)
                db_action_taken = {
                    "operation": "ranking",
                    "count": len(ranking),
                    "visualization": {
                        "type": "gpa_by_student",
                        "title": "GPA leaderboard",
                        "labels": [student["name"] for student in ranking],
                        "values": [student["gpa"] for student in ranking],
                    },
                }

            # ── REPORT: full student profile ─────────────────────────────────
            elif op == "report":
                sid = action.get("student_id")
                report = crud.get_student_report(db, sid)
                if report:
                    s = report["student"]
                    a = report["analytics"]
                    lines = [
                        f"**{s['name']}** — {s['department']}",
                        f"- GPA: **{s['gpa']}** | Status: {s['status']}",
                        f"- Age: {s['age']} | Enrolled: {s['enrollment_year']}",
                        f"- Email: {s['email']}",
                        f"- Overall Rank: #{a['overall_rank']} | "
                        f"Dept Avg GPA: {a['department_avg_gpa']}",
                        f"- Courses enrolled: {a['courses_enrolled']} "
                        f"({a['total_credits']} credits)",
                        "",
                        "**Enrollments:**",
                        "| Course | Grade | Semester |",
                        "|--------|-------|----------|",
                    ]
                    for e in report["enrollments"]:
                        lines.append(
                            f"| {e['course']} | {e['grade']} | {e['semester']} |"
                        )
                    injected_table = "\n".join(lines)
                    db_action_taken = {"operation": "report", "student_id": sid}
                else:
                    injected_table = f"_Student ID {sid} not found._"

            # ── FIND & UPDATE (by name) ──────────────────────────────────────
            elif op == "find_and_update":
                name_query = action.get("name", "")
                matched = crud.get_students(db)  # get all
                matched = [s for s in matched if name_query.lower() in s.name.lower()]
                if matched:
                    target = matched[0]
                    updated = crud.update_student(db, target.id, StudentUpdate(**action["data"]))
                    if updated:
                        db_action_taken = {
                            "operation": "update",
                            "student_id": target.id,
                            "name": target.name,
                        }
                        injected_table = f"✅ Updated **{target.name}** (ID {target.id}) — " + ", ".join(f"{k}: {v}" for k, v in action["data"].items())
                else:
                    injected_table = f"⚠️ No student found matching name: **{name_query}**"

            # ── UPDATE COURSE (by name) ─────────────────────────────────────
            elif op == "update_course":
                course_name = action.get("name", "")
                updated_course, target = crud.find_and_update_course(db, course_name, action.get("data", {}))
                if updated_course:
                    changes = ", ".join(f"{k}: {v}" for k, v in action["data"].items())
                    injected_table = f"✅ Updated **{updated_course.name}** — {changes}"
                    db_action_taken = {
                        "operation": "update_course",
                        "course_id": updated_course.id,
                        "name": updated_course.name,
                    }
                else:
                    injected_table = f"⚠️ No course found matching: **{course_name}**"

            # ── FIND & DELETE (by name) ──────────────────────────────────────
            elif op == "find_and_delete":
                name_query = action.get("name", "")
                matched = crud.get_students(db)
                matched = [s for s in matched if name_query.lower() in s.name.lower()]
                if matched:
                    target = matched[0]
                    if crud.delete_student(db, target.id):
                        db_action_taken = {
                            "operation": "delete",
                            "student_id": target.id,
                            "name": target.name,
                        }
                        injected_table = f"🗑️ Deleted student **{target.name}** (ID {target.id}) from the database."
                else:
                    injected_table = f"⚠️ No student found matching name: **{name_query}**"

            # ── INSERT ───────────────────────────────────────────────────────
            elif op == "insert":
                new_s = crud.create_student(db, StudentCreate(**action["data"]))
                db_action_taken = {
                    "operation": "insert",
                    "student_id": new_s.id,
                    "name": new_s.name,
                }

            # ── UPDATE ───────────────────────────────────────────────────────
            elif op == "update":
                sid = action["student_id"]
                updated = crud.update_student(db, sid, StudentUpdate(**action["data"]))
                if updated:
                    db_action_taken = {"operation": "update", "student_id": sid}

            # ── DELETE ───────────────────────────────────────────────────────
            elif op == "delete":
                sid = action["student_id"]
                if crud.delete_student(db, sid):
                    db_action_taken = {"operation": "delete", "student_id": sid}

        except Exception as e:
            db_action_taken = {"error": str(e)}

    # Explicit breakdown requests answered from summary stats still need a
    # visualization payload for the chat UI.
    request = req.message.lower()
    if db_action_taken is None and (
        ("status" in request and ("breakdown" in request or "distribution" in request))
        or "status breakdown" in request
    ):
        db_action_taken = {
            "operation": "analytics",
            "visualization": {
                "type": "count_by_status",
                "title": "Student status breakdown",
                "labels": ["Active", "Probation", "Graduated"],
                "values": [
                    summary.get("active", 0),
                    summary.get("probation", 0),
                    summary.get("graduated", 0),
                ],
            },
        }
    elif db_action_taken is None and (
        ("department" in request and "gpa" in request)
        or "department performance" in request
    ):
        db_action_taken = {
            "operation": "analytics",
            "visualization": {
                "type": "gpa_by_department",
                "title": "Average GPA by department",
                "labels": [row["department"] for row in dept_stats],
                "values": [row["avg_gpa"] for row in dept_stats],
            },
        }
    elif db_action_taken is None and any(
        term in request for term in ("schema", "tables", "relationships", "database structure")
    ):
        clean_schema_response = (
            "The database contains three tables. Students and courses connect through enrollments, "
            "forming a many-to-many relationship."
        )
        db_action_taken = {
            "operation": "schema",
            "visualization": {"type": "schema_relationships"},
        }
    else:
        clean_schema_response = None

    # ── Build final response ─────────────────────────────────────────────────
    # Remove the raw action block from visible text.
    clean = re.sub(r"```action[\s\S]*?```", "", ai_text).strip()

    if 'clean_schema_response' in locals() and clean_schema_response:
        clean = clean_schema_response

    # Append the real DB results table (for query / ranking / report actions).
    if injected_table:
        clean = f"{clean}\n\n{injected_table}".strip()

    return AgentResponse(response=clean, db_action=db_action_taken)