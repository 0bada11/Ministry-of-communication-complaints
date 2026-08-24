"""Ministry of Communications — complaint intake, routing and tracking API."""

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import repository as repo, services, tasks
from .ai import config as ai_config, ollama, rag
from .ai.store import store as knowledge_store
from .db import UPLOAD_DIR, db_dependency, get_db, init_db, write_db_dependency
from .domain import ComplaintType, Priority, Status
from .schemas import (
    AIHealth,
    ChatReply,
    ChatRequest,
    ComplaintCreate,
    ComplaintCreated,
    ComplaintOut,
    ComplaintUpdate,
    PagedComplaints,
    Stats,
    TrackingOut,
)

logger = logging.getLogger("moct")
logger.setLevel(logging.INFO)
if not logger.handlers:
    # uvicorn configures its own loggers, not the root logger, so a plain
    # logging.info() call here would otherwise go nowhere.
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s"))
    logger.addHandler(_handler)

# How often the priority-escalation sweep runs. A minute keeps it demoable —
# raise this (5-10 minutes) for a real deployment, where the sweep cost still
# matters but instant visibility does not.
ESCALATION_INTERVAL_SECONDS = 60


def _run_escalation_sweep() -> None:
    """One pass over open complaints, bumping priority where it's overdue.

    Runs on a worker thread (see the asyncio.to_thread calls below) since
    sqlite3 is blocking — a slow sweep must never stall request handling.
    """
    with get_db(write=True) as conn:
        escalated = services.escalate_overdue(conn)
    if escalated:
        logger.info("escalated %d complaint(s): %s", len(escalated), escalated)


async def _escalation_loop() -> None:
    while True:
        await asyncio.sleep(ESCALATION_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(_run_escalation_sweep)
        except Exception:
            logger.exception("escalation sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    tasks.start()
    # Catch anything that was already overdue when the server started, rather
    # than waiting a full interval before the first sweep.
    await asyncio.to_thread(_run_escalation_sweep)
    task = asyncio.create_task(_escalation_loop())
    yield
    task.cancel()
    tasks.stop()


app = FastAPI(
    title="منصة شكاوى وزارة الاتصالات — Ministry of Communications Complaints API",
    description=(
        "استقبال شكاوى واستفسارات المواطنين، تصنيفها، تحديد أولويتها، "
        "توجيهها للجهة المسؤولة، ومتابعة حالتها."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# The frontend is served from a different origin during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB = Depends(db_dependency)          # read-only routes
WRITE_DB = Depends(write_db_dependency)  # routes that modify data


def _load(conn: sqlite3.Connection, complaint_id: int) -> dict:
    complaint = repo.get_complaint(conn, complaint_id)
    if not complaint:
        raise HTTPException(404, "الشكوى غير موجودة / complaint not found")
    return complaint


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------

@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/meta", tags=["meta"])
def meta(conn: sqlite3.Connection = DB) -> dict:
    """Statuses, priorities, types, departments and legal transitions."""
    return services.metadata(conn)


# ---------------------------------------------------------------------------
# complaints
# ---------------------------------------------------------------------------

@app.post("/api/complaints", response_model=ComplaintCreated, status_code=201,
          tags=["complaints"])
def create_complaint(
    payload: ComplaintCreate, conn: sqlite3.Connection = WRITE_DB
) -> ComplaintCreated:
    """Submit a complaint as JSON (no attachments)."""
    result = services.create_complaint(conn, payload, files=None)
    # The model reviews the priority on a dedicated worker, so the citizen
    # gets their reference number without waiting on it and the backlog can
    # never occupy a request thread.
    tasks.submit(services.refine_priority, result["complaint"]["id"])
    return ComplaintCreated(
        complaint=services.complaint_view(conn, result["complaint"]),
        auto_classified=result["auto_classified"],
        confidence=result["confidence"],
        possible_duplicates=result["possible_duplicates"],
    )


@app.post("/api/complaints/upload", response_model=ComplaintCreated, status_code=201,
          tags=["complaints"])
def create_complaint_with_files(
    citizen_name: str = Form(...),
    citizen_phone: str = Form(...),
    governorate: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    citizen_email: str | None = Form(None),
    location_detail: str | None = Form(None),
    type: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    conn: sqlite3.Connection = WRITE_DB,
) -> ComplaintCreated:
    """Submit a complaint as multipart/form-data with up to 5 attachments."""
    payload = ComplaintCreate(
        citizen_name=citizen_name,
        citizen_phone=citizen_phone,
        citizen_email=citizen_email or None,
        governorate=governorate,
        location_detail=location_detail or None,
        title=title,
        description=description,
        type=type or None,
    )
    result = services.create_complaint(conn, payload, files=files)
    tasks.submit(services.refine_priority, result["complaint"]["id"])
    return ComplaintCreated(
        complaint=services.complaint_view(conn, result["complaint"]),
        auto_classified=result["auto_classified"],
        confidence=result["confidence"],
        possible_duplicates=result["possible_duplicates"],
    )


@app.get("/api/complaints", response_model=PagedComplaints, tags=["complaints"])
def list_complaints(
    status: list[Status] = Query(default=[]),
    type: list[ComplaintType] = Query(default=[]),
    priority: list[Priority] = Query(default=[]),
    department: str | None = None,
    assignee: str | None = None,
    q: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    page: int = 1,
    per_page: int = 20,
    conn: sqlite3.Connection = DB,
) -> PagedComplaints:
    """Filter, search, sort and paginate complaints for the staff dashboard."""
    rows, total = repo.search_complaints(
        conn,
        status=[s.value for s in status],
        type_=[t.value for t in type],
        priority=[p.value for p in priority],
        department_code=department,
        assignee=assignee,
        q=q,
        sort=sort,
        order=order,
        page=page,
        per_page=per_page,
    )
    # One lookup for the whole page instead of a query per row.
    departments = {d["id"]: d for d in repo.list_departments(conn)}
    per_page = max(1, min(per_page, 100))
    return PagedComplaints(
        items=[services.summary_view(r, departments) for r in rows],
        total=total,
        page=max(1, page),
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@app.get("/api/complaints.csv", tags=["complaints"])
def export_complaints(
    status: list[Status] = Query(default=[]),
    type: list[ComplaintType] = Query(default=[]),
    priority: list[Priority] = Query(default=[]),
    department: str | None = None,
    q: str | None = None,
    conn: sqlite3.Connection = DB,
) -> Response:
    """Same filters as the list endpoint, returned as a CSV download."""
    rows, _ = repo.search_complaints(
        conn,
        status=[s.value for s in status],
        type_=[t.value for t in type],
        priority=[p.value for p in priority],
        department_code=department,
        q=q,
        per_page=100,
        page=1,
    )
    # UTF-8 BOM so Excel opens the Arabic columns correctly.
    body = "﻿" + services.to_csv(conn, rows)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="complaints.csv"'},
    )


@app.get("/api/complaints/{complaint_id}", response_model=ComplaintOut,
         tags=["complaints"])
def get_complaint(complaint_id: int, conn: sqlite3.Connection = DB) -> ComplaintOut:
    return services.complaint_view(conn, _load(conn, complaint_id))


@app.patch("/api/complaints/{complaint_id}", response_model=ComplaintOut,
           tags=["complaints"])
def update_complaint(
    complaint_id: int, payload: ComplaintUpdate, conn: sqlite3.Connection = WRITE_DB
) -> ComplaintOut:
    """Change status, priority, type, department, assignee or resolution."""
    complaint = _load(conn, complaint_id)
    updated = services.apply_update(conn, complaint, payload)
    return services.complaint_view(conn, updated)


@app.delete("/api/complaints/{complaint_id}", status_code=204, tags=["complaints"])
def delete_complaint(complaint_id: int, conn: sqlite3.Connection = WRITE_DB) -> None:
    complaint = _load(conn, complaint_id)
    for attachment in repo.list_attachments(conn, complaint_id):
        (UPLOAD_DIR / attachment["stored_name"]).unlink(missing_ok=True)
    repo.delete_complaint(conn, complaint["id"])


@app.get("/api/complaints/{complaint_id}/events", tags=["complaints"])
def complaint_events(complaint_id: int, conn: sqlite3.Connection = DB) -> list[dict]:
    """The full update log for one complaint."""
    _load(conn, complaint_id)
    return repo.list_events(conn, complaint_id)


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------

@app.post("/api/complaints/{complaint_id}/attachments", status_code=201,
          tags=["attachments"])
def upload_attachments(
    complaint_id: int,
    files: list[UploadFile] = File(...),
    actor: str = Form("موظف"),
    conn: sqlite3.Connection = WRITE_DB,
) -> list[dict]:
    _load(conn, complaint_id)
    saved = services.save_attachments(conn, complaint_id, files, actor)
    return [services.attachment_view(a) for a in saved]


@app.get("/api/attachments/{attachment_id}", tags=["attachments"])
def download_attachment(attachment_id: int, conn: sqlite3.Connection = DB) -> FileResponse:
    attachment = repo.get_attachment(conn, attachment_id)
    if not attachment:
        raise HTTPException(404, "المرفق غير موجود / attachment not found")
    path = UPLOAD_DIR / attachment["stored_name"]
    if not path.exists():
        raise HTTPException(404, "الملف مفقود على الخادم / file missing on disk")
    return FileResponse(
        path,
        media_type=attachment["content_type"] or "application/octet-stream",
        filename=attachment["filename"],
    )


# ---------------------------------------------------------------------------
# public tracking
# ---------------------------------------------------------------------------

@app.get("/api/track/{reference_no}", response_model=TrackingOut, tags=["tracking"])
def track(reference_no: str, conn: sqlite3.Connection = DB) -> TrackingOut:
    """Look a complaint up by its reference number — no contact details returned."""
    complaint = repo.get_by_reference(conn, reference_no)
    if not complaint:
        raise HTTPException(404, "رقم مرجعي غير صحيح / unknown reference number")
    return services.tracking_view(conn, complaint)


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------

@app.get("/api/stats", response_model=Stats, tags=["dashboard"])
def dashboard_stats(days: int = 14, conn: sqlite3.Connection = DB) -> Stats:
    """Counts by status, type, priority and department, plus a daily trend."""
    return repo.stats(conn, recent_days=max(1, min(days, 90)))


# ---------------------------------------------------------------------------
# assistant
# ---------------------------------------------------------------------------

@app.get("/api/ai/health", response_model=AIHealth, tags=["assistant"])
def ai_health() -> AIHealth:
    """Whether the assistant can answer, and what it is running on."""
    return AIHealth(
        enabled=ai_config.AI_ENABLED,
        available=ollama.available(),
        llm_model=ai_config.LLM_MODEL,
        embed_model=ai_config.EMBED_MODEL,
        indexed_chunks=knowledge_store.count(),
    )


@app.post("/api/chat", response_model=ChatReply, tags=["assistant"])
def chat(payload: ChatRequest) -> ChatReply:
    """Answer a citizen's question from the platform's own documentation.

    Grounded in the indexed knowledge base: when retrieval finds nothing
    relevant the assistant says so and points at the service centre rather
    than inventing a policy.
    """
    result = rag.answer(
        payload.message,
        [{"role": m.role, "content": m.content} for m in payload.history],
    )
    return ChatReply(**result)


# ---------------------------------------------------------------------------
# frontend
# ---------------------------------------------------------------------------

# Mounted last so it never shadows an /api route. One server serves both.
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
