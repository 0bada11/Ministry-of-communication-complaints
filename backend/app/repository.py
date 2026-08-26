"""All SQL lives here. Routes stay thin; queries stay reviewable in one place."""

import re
import sqlite3
from datetime import datetime, timedelta, timezone

from .domain import (
    LABELS,
    SLA_HOURS,
    SLA_WARNING_RATIO,
    STATUS_COLORS,
    TERMINAL,
    TERMINAL_SQL,
    TYPE_COLORS,
    ComplaintType,
    Status,
)

REFERENCE_PREFIX = "MOCT"
# References start here so the first issued number already looks like a real
# case file rather than 000001.
REFERENCE_BASE = 14000


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_reference(conn: sqlite3.Connection) -> str:
    """Sequential, human-quotable reference: MOCT-2026-014287."""
    year = datetime.now(timezone.utc).year
    prefix = f"{REFERENCE_PREFIX}-{year}-"
    issued = conn.execute(
        "SELECT COUNT(*) FROM complaints WHERE reference_no LIKE ?", (f"{prefix}%",)
    ).fetchone()[0]

    # Walk forward past any gap left by deleted complaints.
    for offset in range(1, 1000):
        ref = f"{prefix}{REFERENCE_BASE + issued + offset:06d}"
        taken = conn.execute(
            "SELECT 1 FROM complaints WHERE reference_no = ?", (ref,)
        ).fetchone()
        if not taken:
            return ref
    raise RuntimeError("could not allocate a unique reference number")


# ---------------------------------------------------------------------------
# departments
# ---------------------------------------------------------------------------

def list_departments(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM departments ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def department_by_code(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute("SELECT * FROM departments WHERE code = ?", (code,)).fetchone()
    return dict(row) if row else None


def department_by_id(conn: sqlite3.Connection, dept_id: int | None) -> dict | None:
    if dept_id is None:
        return None
    row = conn.execute("SELECT * FROM departments WHERE id = ?", (dept_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# events (the update log / history trail)
# ---------------------------------------------------------------------------

def add_event(
    conn: sqlite3.Connection,
    complaint_id: int,
    action: str,
    *,
    field: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    note: str | None = None,
    actor: str = "system",
) -> None:
    conn.execute(
        "INSERT INTO events (complaint_id, action, field, old_value, new_value,"
        " note, actor, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (complaint_id, action, field, old_value, new_value, note, actor, now()),
    )


def list_events(conn: sqlite3.Connection, complaint_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM events WHERE complaint_id = ? ORDER BY id", (complaint_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------

def add_attachment(
    conn: sqlite3.Connection,
    complaint_id: int,
    filename: str,
    stored_name: str,
    content_type: str | None,
    size: int,
) -> int:
    cur = conn.execute(
        "INSERT INTO attachments (complaint_id, filename, stored_name,"
        " content_type, size, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (complaint_id, filename, stored_name, content_type, size, now()),
    )
    return int(cur.lastrowid)


def list_attachments(conn: sqlite3.Connection, complaint_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM attachments WHERE complaint_id = ? ORDER BY id", (complaint_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_attachment(conn: sqlite3.Connection, attachment_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# complaints
# ---------------------------------------------------------------------------

def create_complaint(conn: sqlite3.Connection, data: dict) -> int:
    stamp = now()
    cur = conn.execute(
        """
        INSERT INTO complaints (
            reference_no, citizen_name, citizen_phone, citizen_email, governorate,
            location_detail, title, description, type, priority, status,
            department_id, created_at, updated_at
        ) VALUES (
            :reference_no, :citizen_name, :citizen_phone, :citizen_email, :governorate,
            :location_detail, :title, :description, :type, :priority, :status,
            :department_id, :created_at, :updated_at
        )
        """,
        {**data, "created_at": stamp, "updated_at": stamp},
    )
    return int(cur.lastrowid)


def get_complaint(conn: sqlite3.Connection, complaint_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM complaints WHERE id = ?", (complaint_id,)
    ).fetchone()
    return dict(row) if row else None


def get_by_reference(conn: sqlite3.Connection, reference_no: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM complaints WHERE reference_no = ? COLLATE NOCASE",
        (reference_no.strip(),),
    ).fetchone()
    return dict(row) if row else None


def update_complaint(conn: sqlite3.Connection, complaint_id: int, changes: dict) -> None:
    if not changes:
        return
    changes = {**changes, "updated_at": now()}
    assignments = ", ".join(f"{key} = :{key}" for key in changes)
    conn.execute(
        f"UPDATE complaints SET {assignments} WHERE id = :id",
        {**changes, "id": complaint_id},
    )


def delete_complaint(conn: sqlite3.Connection, complaint_id: int) -> None:
    conn.execute("DELETE FROM complaints WHERE id = ?", (complaint_id,))


def open_complaints_with_age(conn: sqlite3.Connection) -> list[dict]:
    """Open, not-yet-high complaints with how long they have held their priority.

    The clock restarts at the last priority change, not at submission: the
    escalation ladder is meant to be climbed one rung per SLA window, and a
    clock that never resets would let a single stale complaint climb every rung
    on consecutive sweeps.

    Closed and already-high complaints are excluded up front since neither can
    escalate further.
    """
    rows = conn.execute(
        f"""
        SELECT c.id, c.priority, c.type,
               (julianday('now') - julianday(COALESCE(
                   (SELECT MAX(e.created_at) FROM events e
                     WHERE e.complaint_id = c.id
                       AND e.action = 'priority_changed'),
                   c.created_at
               ))) * 24.0 AS hours_at_priority
        FROM complaints c
        WHERE c.status NOT IN ({TERMINAL_SQL}) AND c.priority != 'high'
        """
    ).fetchall()
    return [dict(r) for r in rows]


# Strips the separators people type into a phone number, so a stored
# "+963 955-512345" compares equal to a searched "0955512345".
_PHONE_DIGITS = (
    "REPLACE(REPLACE(REPLACE(REPLACE(c.citizen_phone,' ',''),'-',''),'(',''),')','')"
)

# Whitelist of sortable columns — the sort key is interpolated into SQL, so it
# must never come straight from the query string.
SORTABLE = {
    "created_at": "c.created_at",
    "updated_at": "c.updated_at",
    "priority": (
        "CASE c.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"
    ),
    "status": "c.status",
    "reference_no": "c.reference_no",
}


def search_complaints(
    conn: sqlite3.Connection,
    *,
    status: list[str] | None = None,
    type_: list[str] | None = None,
    priority: list[str] | None = None,
    department_code: str | None = None,
    assignee: str | None = None,
    archived: bool | None = False,
    q: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict], int]:
    """Filtered, sorted, paginated list. Returns (rows, total_matching).

    `archived` is a three-state filter, not a boolean: False (the default)
    hides archived complaints, True shows only them, and None ignores the
    distinction entirely. Defaulting to False is what keeps the archive out of
    the working queue without every caller having to remember to ask.

    It filters on the status itself rather than on `archived_at`, which is only
    a stamp of when the complaint was last filed and — like `closed_at` — is
    never cleared when the complaint comes back out.
    """
    where: list[str] = []
    params: dict = {}

    def add_in(column: str, values: list[str] | None, key: str) -> None:
        if not values:
            return
        placeholders = [f":{key}{i}" for i in range(len(values))]
        where.append(f"c.{column} IN ({', '.join(placeholders)})")
        params.update({f"{key}{i}": v for i, v in enumerate(values)})

    add_in("status", status, "st")
    add_in("type", type_, "ty")
    add_in("priority", priority, "pr")

    if archived is not None:
        where.append("c.status = :arch" if archived else "c.status != :arch")
        params["arch"] = Status.ARCHIVED.value

    if department_code:
        where.append("d.code = :dept")
        params["dept"] = department_code
    if assignee:
        where.append("c.assignee = :assignee")
        params["assignee"] = assignee
    if q:
        conditions = [
            "c.title LIKE :q", "c.description LIKE :q", "c.reference_no LIKE :q",
            "c.citizen_name LIKE :q", "c.citizen_phone LIKE :q",
            "c.location_detail LIKE :q",
        ]
        params["q"] = f"%{q.strip()}%"

        # Staff paste phone numbers with spaces, dashes or a +963 prefix. Strip
        # every separator from both the stored number and the query so
        # "0955 512 345" still finds "0955512345".
        digits = re.sub(r"\D", "", q)
        if len(digits) >= 4:
            conditions.append(f"{_PHONE_DIGITS} LIKE :qphone")
            params["qphone"] = f"%{digits}%"

        where.append(f"({' OR '.join(conditions)})")

    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = conn.execute(
        "SELECT COUNT(*) FROM complaints c"
        f" LEFT JOIN departments d ON d.id = c.department_id {clause}",
        params,
    ).fetchone()[0]

    order_sql = SORTABLE.get(sort, SORTABLE["created_at"])
    direction = "ASC" if order.lower() == "asc" else "DESC"
    per_page = max(1, min(per_page, 100))
    page = max(1, page)

    rows = conn.execute(
        f"""
        SELECT c.*,
               (SELECT COUNT(*) FROM attachments a WHERE a.complaint_id = c.id)
                   AS attachment_count
        FROM complaints c
        LEFT JOIN departments d ON d.id = c.department_id
        {clause}
        ORDER BY {order_sql} {direction}, c.id DESC
        LIMIT :limit OFFSET :offset
        """,
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).fetchall()
    return [dict(r) for r in rows], int(total)


def recent_for_duplicates(
    conn: sqlite3.Connection, ctype: str, days: int = 30
) -> list[dict]:
    """Same-type complaints from the last N days, for similarity comparison."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT id, reference_no, title, description, status FROM complaints"
        " WHERE type = ? AND created_at >= ? ORDER BY created_at DESC LIMIT 200",
        (ctype, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------

def _count_by(conn: sqlite3.Connection, column: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {column} AS key, COUNT(*) AS n FROM complaints GROUP BY {column}"
    ).fetchall()
    return {r["key"]: r["n"] for r in rows}


def _sla_buckets(conn: sqlite3.Connection) -> dict[str, int]:
    """Split every complaint into within / near / overdue against its SLA window.

    Resolved complaints are measured against how long they actually took; open
    ones against how long they have been waiting so far.
    """
    targets = " ".join(
        f"WHEN '{priority.value}' THEN {hours}" for priority, hours in SLA_HOURS.items()
    )
    row = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN elapsed > target THEN 1 ELSE 0 END) AS overdue,
            SUM(CASE WHEN elapsed > target * :warn AND elapsed <= target
                     THEN 1 ELSE 0 END) AS near,
            SUM(CASE WHEN elapsed <= target * :warn THEN 1 ELSE 0 END) AS within
        FROM (
            SELECT
                (julianday(COALESCE(resolved_at, 'now')) - julianday(created_at))
                    * 24.0 AS elapsed,
                CASE priority {targets} ELSE 72 END AS target
            FROM complaints
        )
        """,
        {"warn": SLA_WARNING_RATIO},
    ).fetchone()
    return {key: int(row[key] or 0) for key in ("within", "near", "overdue")}


def _overdue_open(conn: sqlite3.Connection) -> int:
    """Open complaints already past their SLA window."""
    targets = " ".join(
        f"WHEN '{priority.value}' THEN {hours}" for priority, hours in SLA_HOURS.items()
    )
    return int(conn.execute(
        f"""
        SELECT COUNT(*) FROM complaints
        WHERE status NOT IN ({TERMINAL_SQL})
          AND (julianday('now') - julianday(created_at)) * 24.0
              > CASE priority {targets} ELSE 72 END
        """
    ).fetchone()[0])


def _percentages(counts: dict[str, int], total: int) -> dict[str, float]:
    """Whole-number percentages that still add up to 100."""
    if total <= 0:
        return {key: 0.0 for key in counts}
    raw = {key: value / total * 100 for key, value in counts.items()}
    rounded = {key: int(value) for key, value in raw.items()}
    # Hand the rounding remainder to the largest fractional parts.
    remainder = 100 - sum(rounded.values())
    for key in sorted(raw, key=lambda k: raw[k] - rounded[k], reverse=True):
        if remainder <= 0:
            break
        rounded[key] += 1
        remainder -= 1
    return {key: float(value) for key, value in rounded.items()}


def stats(conn: sqlite3.Connection, recent_days: int = 14) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    by_status = _count_by(conn, "status")
    by_type = _count_by(conn, "type")
    by_priority = _count_by(conn, "priority")

    dept_rows = conn.execute(
        "SELECT d.code AS key, d.name_ar AS name, COUNT(c.id) AS n FROM departments d"
        " LEFT JOIN complaints c ON c.department_id = d.id GROUP BY d.code, d.name_ar"
    ).fetchall()
    by_department = {r["key"]: r["n"] for r in dept_rows}

    open_count = sum(
        by_status.get(s.value, 0)
        for s in (Status.NEW, Status.ASSIGNED, Status.IN_PROGRESS)
    )
    resolved_count = sum(by_status.get(s.value, 0) for s in TERMINAL)

    avg_hours = conn.execute(
        "SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 24.0)"
        " FROM complaints WHERE resolved_at IS NOT NULL"
    ).fetchone()[0]

    today = datetime.now(timezone.utc).date()
    new_today = int(conn.execute(
        "SELECT COUNT(*) FROM complaints WHERE substr(created_at, 1, 10) = ?",
        (today.isoformat(),),
    ).fetchone()[0])
    new_yesterday = int(conn.execute(
        "SELECT COUNT(*) FROM complaints WHERE substr(created_at, 1, 10) = ?",
        ((today - timedelta(days=1)).isoformat(),),
    ).fetchone()[0])
    resolved_this_week = int(conn.execute(
        "SELECT COUNT(*) FROM complaints WHERE resolved_at IS NOT NULL"
        " AND substr(resolved_at, 1, 10) >= ?",
        ((today - timedelta(days=6)).isoformat(),),
    ).fetchone()[0])

    # Per-day counts for the trend chart, zero-filled so the bars have no gaps.
    start = today - timedelta(days=recent_days - 1)
    counted = {
        r["day"]: r["n"]
        for r in conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n FROM complaints"
            " WHERE substr(created_at, 1, 10) >= ? GROUP BY day",
            (start.isoformat(),),
        ).fetchall()
    }
    trend = [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "count": counted.get((start + timedelta(days=i)).isoformat(), 0),
        }
        for i in range(recent_days)
    ]

    # Status breakdown for the donut, in the fixed order the legend lists.
    status_counts = {s.value: by_status.get(s.value, 0) for s in Status}
    status_pct = _percentages(status_counts, total)
    status_breakdown = [
        {
            "status": s.value,
            "label_ar": LABELS["status"][s]["ar"],
            "count": status_counts[s.value],
            "percent": status_pct[s.value],
            "color": STATUS_COLORS[s],
        }
        for s in Status
    ]

    # Type breakdown for the horizontal bars, widest bar normalized to 100%.
    type_counts = {t.value: by_type.get(t.value, 0) for t in ComplaintType}
    busiest = max(type_counts.values(), default=0)
    type_breakdown = sorted(
        (
            {
                "type": t.value,
                "label_ar": LABELS["type"][t]["ar"],
                "count": type_counts[t.value],
                "width": round(type_counts[t.value] / busiest * 100) if busiest else 0,
                "color": TYPE_COLORS[t],
            }
            for t in ComplaintType
        ),
        key=lambda item: item["count"],
        reverse=True,
    )

    buckets = _sla_buckets(conn)
    sla_pct = _percentages(buckets, sum(buckets.values()))

    return {
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
        "by_priority": by_priority,
        "by_department": by_department,
        "departments": [
            {"code": r["key"], "name_ar": r["name"], "count": r["n"]} for r in dept_rows
        ],
        "open_count": open_count,
        "resolved_count": resolved_count,
        "avg_resolution_hours": round(avg_hours, 1) if avg_hours is not None else None,
        "new_today": new_today,
        "new_yesterday": new_yesterday,
        "in_progress_count": by_status.get(Status.IN_PROGRESS.value, 0),
        "overdue_count": _overdue_open(conn),
        "resolved_this_week": resolved_this_week,
        "sla": {"counts": buckets, "percent": sla_pct},
        "status_breakdown": status_breakdown,
        "type_breakdown": type_breakdown,
        "recent_days": trend,
    }
