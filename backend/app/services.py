"""Business rules that sit between the routes and the SQL.

Creating a complaint, applying an update, saving files and shaping rows into API
responses all live here so the route handlers stay declarative.
"""

import re
import sqlite3
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from . import classifier, repository as repo
from .db import UPLOAD_DIR
from .domain import (
    ALLOWED_TRANSITIONS,
    FLOW,
    GOVERNORATES,
    LABELS,
    ROUTING,
    STATUS_COLORS,
    TYPE_CODES,
    TYPE_COLORS,
    TYPE_DESCRIPTIONS,
    ComplaintType,
    Priority,
    Status,
    escalate_priority,
)

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB per file
MAX_ATTACHMENTS = 5
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".pdf", ".doc", ".docx", ".txt", ".mp4", ".mp3",
}
DUPLICATE_THRESHOLD = 0.72


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------

def _safe_name(filename: str) -> str:
    """Strip any path component and keep the extension only if we allow it."""
    base = Path(filename or "file").name
    base = re.sub(r"[^\w\s.\-؀-ۿ]", "_", base).strip() or "file"
    return base[:120]


def save_attachments(
    conn: sqlite3.Connection, complaint_id: int, files: list[UploadFile], actor: str
) -> list[dict]:
    """Persist uploads to disk and record them. Rejects bad type or oversize."""
    existing = len(repo.list_attachments(conn, complaint_id))
    incoming = [f for f in files if f and f.filename]
    if existing + len(incoming) > MAX_ATTACHMENTS:
        raise HTTPException(
            400,
            f"الحد الأقصى {MAX_ATTACHMENTS} مرفقات / at most"
            f" {MAX_ATTACHMENTS} attachments per complaint",
        )

    saved = []
    for upload in incoming:
        name = _safe_name(upload.filename)
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"نوع ملف غير مسموح / file type not allowed: {suffix}")

        payload = upload.file.read()
        if len(payload) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                400, f"الملف أكبر من الحد المسموح / file too large: {name}"
            )
        if not payload:
            continue

        stored_name = f"{uuid.uuid4().hex}{suffix}"
        (UPLOAD_DIR / stored_name).write_bytes(payload)

        attachment_id = repo.add_attachment(
            conn, complaint_id, name, stored_name, upload.content_type, len(payload)
        )
        repo.add_event(
            conn, complaint_id, "attachment_added", new_value=name, actor=actor
        )
        saved.append(repo.get_attachment(conn, attachment_id))
    return saved


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

def find_duplicates(
    conn: sqlite3.Connection,
    ctype: str,
    title: str,
    description: str,
    exclude_id: int | None = None,
) -> list[dict]:
    """Recent same-type complaints whose text is close enough to flag.

    `exclude_id` keeps a freshly inserted complaint from matching itself.
    """
    text = f"{title} {description}"
    hits = []
    for row in repo.recent_for_duplicates(conn, ctype):
        if row["id"] == exclude_id:
            continue
        score = classifier.similarity(text, f"{row['title']} {row['description']}")
        if score >= DUPLICATE_THRESHOLD:
            hits.append(
                {
                    "reference_no": row["reference_no"],
                    "title": row["title"],
                    "similarity": round(score, 2),
                    "status": row["status"],
                }
            )
    return sorted(hits, key=lambda h: h["similarity"], reverse=True)[:3]


def create_complaint(conn: sqlite3.Connection, payload, files: list[UploadFile] | None) -> dict:
    """Triage, persist, route and log a new complaint."""
    triaged = classifier.triage(payload.title, payload.description)

    # An explicit choice from the citizen always beats the inferred one.
    ctype = payload.type or triaged["type"]
    priority = payload.priority or triaged["priority"]
    auto_classified = payload.type is None
    department = repo.department_by_code(conn, classifier.route(ctype))

    reference_no = repo.make_reference(conn)
    complaint_id = repo.create_complaint(
        conn,
        {
            "reference_no": reference_no,
            "citizen_name": payload.citizen_name.strip(),
            "citizen_phone": payload.citizen_phone.strip(),
            "citizen_email": payload.citizen_email,
            "governorate": payload.governorate,
            "location_detail": (payload.location_detail or "").strip() or None,
            "title": payload.title.strip(),
            "description": payload.description.strip(),
            "type": ctype.value,
            "priority": priority.value,
            # Auto-routing picks the owning department immediately, but the
            # complaint stays 'New' until a person in that department takes it.
            "status": Status.NEW.value,
            "department_id": department["id"] if department else None,
        },
    )

    repo.add_event(
        conn, complaint_id, "created", new_value=reference_no, actor=payload.citizen_name
    )
    repo.add_event(
        conn,
        complaint_id,
        "classified",
        field="type",
        new_value=ctype.value,
        note=("تصنيف تلقائي" if auto_classified else "تصنيف من مقدّم الشكوى"),
        actor="system" if auto_classified else payload.citizen_name,
    )
    # The citizen's pick wins, but a disagreeing classifier is worth recording
    # so the reviewing officer can reclassify with one click.
    if not auto_classified and triaged["type"] is not ctype:
        repo.add_event(
            conn,
            complaint_id,
            "classification_suggested",
            field="type",
            old_value=ctype.value,
            new_value=triaged["type"].value,
            note=f"يقترح النظام تصنيفاً مختلفاً (ثقة {triaged['confidence']:.0%})",
            actor="system",
        )
    if department:
        repo.add_event(
            conn,
            complaint_id,
            "routed",
            field="department",
            new_value=department["name_ar"],
            note="توجيه تلقائي حسب نوع الشكوى",
            actor="system",
        )

    if files:
        save_attachments(conn, complaint_id, files, payload.citizen_name)

    return {
        "complaint": repo.get_complaint(conn, complaint_id),
        "auto_classified": auto_classified,
        "confidence": triaged["confidence"],
        "possible_duplicates": find_duplicates(
            conn, ctype.value, payload.title, payload.description,
            exclude_id=complaint_id,
        ),
    }


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def apply_update(conn: sqlite3.Connection, complaint: dict, payload) -> dict:
    """Validate a PATCH, write the changed columns, and log one event per field."""
    complaint_id = complaint["id"]
    changes: dict = {}
    actor = payload.actor

    if payload.status and payload.status.value != complaint["status"]:
        current = Status(complaint["status"])
        if payload.status not in ALLOWED_TRANSITIONS[current]:
            raise HTTPException(
                400,
                f"انتقال غير مسموح / illegal transition:"
                f" {current.value} -> {payload.status.value}",
            )
        changes["status"] = payload.status.value
        if payload.status is Status.RESOLVED:
            changes["resolved_at"] = repo.now()
        elif payload.status is Status.CLOSED:
            changes["closed_at"] = repo.now()
            # Closing something never marked resolved still needs a resolution time.
            if not complaint["resolved_at"]:
                changes["resolved_at"] = repo.now()
        repo.add_event(
            conn, complaint_id, "status_changed", field="status",
            old_value=complaint["status"], new_value=payload.status.value,
            note=payload.note, actor=actor,
        )

    if payload.priority and payload.priority.value != complaint["priority"]:
        changes["priority"] = payload.priority.value
        repo.add_event(
            conn, complaint_id, "priority_changed", field="priority",
            old_value=complaint["priority"], new_value=payload.priority.value,
            actor=actor,
        )

    if payload.type and payload.type.value != complaint["type"]:
        changes["type"] = payload.type.value
        repo.add_event(
            conn, complaint_id, "reclassified", field="type",
            old_value=complaint["type"], new_value=payload.type.value, actor=actor,
        )

    if payload.department_code:
        department = repo.department_by_code(conn, payload.department_code)
        if not department:
            raise HTTPException(404, "الجهة غير موجودة / unknown department")
        if department["id"] != complaint["department_id"]:
            previous = repo.department_by_id(conn, complaint["department_id"])
            changes["department_id"] = department["id"]
            repo.add_event(
                conn, complaint_id, "routed", field="department",
                old_value=previous["name_ar"] if previous else None,
                new_value=department["name_ar"], note=payload.note, actor=actor,
            )

    if (payload.location_detail is not None
            and payload.location_detail != complaint["location_detail"]):
        changes["location_detail"] = payload.location_detail
        repo.add_event(
            conn, complaint_id, "location_updated", field="location_detail",
            new_value=payload.location_detail, actor=actor,
        )

    if payload.assignee is not None and payload.assignee != complaint["assignee"]:
        changes["assignee"] = payload.assignee
        # Naming an owner is what takes a complaint off the 'New' pile.
        if complaint["status"] == Status.NEW.value and "status" not in changes:
            changes["status"] = Status.ASSIGNED.value
            repo.add_event(
                conn, complaint_id, "status_changed", field="status",
                old_value=Status.NEW.value, new_value=Status.ASSIGNED.value,
                actor=actor,
            )
        repo.add_event(
            conn, complaint_id, "assigned", field="assignee",
            old_value=complaint["assignee"], new_value=payload.assignee, actor=actor,
        )

    if payload.resolution is not None and payload.resolution != complaint["resolution"]:
        changes["resolution"] = payload.resolution
        repo.add_event(
            conn, complaint_id, "resolution_added", field="resolution",
            new_value=payload.resolution, actor=actor,
        )

    # A note on its own is still a log entry worth keeping.
    if payload.note and not changes:
        repo.add_event(conn, complaint_id, "note", note=payload.note, actor=actor)

    repo.update_complaint(conn, complaint_id, changes)
    return repo.get_complaint(conn, complaint_id)


# ---------------------------------------------------------------------------
# automatic escalation
# ---------------------------------------------------------------------------

def escalate_overdue(conn: sqlite3.Connection) -> list[int]:
    """Bump the priority of any open complaint that has waited too long.

    Runs on a timer from `main.py` rather than per-request, so an ordinary
    page view never pays for a write. Every bump is logged like any other
    priority change, with `actor="system"` and a note explaining why, so it
    shows up in the complaint's update log exactly like a human-made change.
    Returns the ids that were escalated, mainly for logging and tests.
    """
    escalated = []
    for row in repo.open_complaints_with_age(conn):
        current = Priority(row["priority"])
        new = escalate_priority(row["hours_open"], current)
        if new is current:
            continue
        repo.update_complaint(conn, row["id"], {"priority": new.value})
        repo.add_event(
            conn, row["id"], "priority_changed", field="priority",
            old_value=current.value, new_value=new.value,
            note=f"تصعيد تلقائي بعد {round(row['hours_open'])} ساعة دون حل",
            actor="system",
        )
        escalated.append(row["id"])
    return escalated


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------

def attachment_view(row: dict) -> dict:
    return {**row, "url": f"/api/attachments/{row['id']}"}


def complaint_view(conn: sqlite3.Connection, row: dict) -> dict:
    """Full detail view: department expanded, attachments and history included."""
    return {
        **row,
        "department": repo.department_by_id(conn, row["department_id"]),
        "attachments": [
            attachment_view(a) for a in repo.list_attachments(conn, row["id"])
        ],
        "events": repo.list_events(conn, row["id"]),
    }


def summary_view(row: dict, departments: dict) -> dict:
    return {**row, "department": departments.get(row["department_id"])}


def tracking_view(conn: sqlite3.Connection, row: dict) -> dict:
    """Public view — deliberately omits the citizen's contact details."""
    return {
        "reference_no": row["reference_no"],
        "title": row["title"],
        "type": row["type"],
        "status": row["status"],
        "priority": row["priority"],
        "department": repo.department_by_id(conn, row["department_id"]),
        "resolution": row["resolution"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "events": repo.list_events(conn, row["id"]),
    }


def metadata(conn: sqlite3.Connection) -> dict:
    """Everything the frontend needs to render cards, dropdowns and badges."""
    departments = {d["code"]: d for d in repo.list_departments(conn)}

    def options(group: str, enum_cls) -> list[dict]:
        return [{"value": member.value, **LABELS[group][member]} for member in enum_cls]

    # The category cards need the code, blurb and owning department alongside
    # the label, so types carry more than the other two vocabularies.
    types = [
        {
            "value": ctype.value,
            **LABELS["type"][ctype],
            "code": TYPE_CODES[ctype],
            "description": TYPE_DESCRIPTIONS[ctype],
            "department": departments.get(ROUTING[ctype]),
            "color": TYPE_COLORS[ctype],
        }
        for ctype in ComplaintType
    ]

    return {
        "statuses": [
            {**option, "color": STATUS_COLORS[Status(option["value"])]}
            for option in options("status", Status)
        ],
        "priorities": options("priority", Priority),
        "types": types,
        "departments": list(departments.values()),
        "governorates": GOVERNORATES,
        "flow": [status.value for status in FLOW],
        "transitions": {
            status.value: sorted(s.value for s in targets)
            for status, targets in ALLOWED_TRANSITIONS.items()
        },
    }


def next_status(current: str) -> Status | None:
    """The following step in the workflow, or None once the complaint is closed."""
    index = FLOW.index(Status(current))
    return FLOW[index + 1] if index + 1 < len(FLOW) else None


def to_csv(conn: sqlite3.Connection, rows: list[dict]) -> str:
    """Export rows for the dashboard's 'تصدير CSV' button."""
    departments = {d["id"]: d for d in repo.list_departments(conn)}
    header = [
        "الرقم المرجعي", "الموضوع", "التصنيف", "الدائرة", "الأولوية", "الحالة",
        "المحافظة", "العنوان التفصيلي", "مقدّم الشكوى", "رقم الموبايل", "المسؤول",
        "تاريخ الاستلام", "آخر تحديث",
    ]
    lines = [",".join(header)]
    for row in rows:
        department = departments.get(row["department_id"])
        values = [
            row["reference_no"],
            row["title"],
            LABELS["type"][ComplaintType(row["type"])]["ar"],
            department["name_ar"] if department else "—",
            LABELS["priority"][Priority(row["priority"])]["ar"],
            LABELS["status"][Status(row["status"])]["ar"],
            row["governorate"] or "—",
            row["location_detail"] or "—",
            row["citizen_name"],
            row["citizen_phone"],
            row["assignee"] or "—",
            row["created_at"],
            row["updated_at"],
        ]
        lines.append(",".join(f'"{str(v).replace(chr(34), chr(34) * 2)}"' for v in values))
    return "\n".join(lines)
