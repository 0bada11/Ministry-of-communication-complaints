"""Request and response models."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from .domain import ComplaintType, Priority, Status


class ComplaintCreate(BaseModel):
    citizen_name: str = Field(min_length=2, max_length=120)
    citizen_phone: str = Field(min_length=6, max_length=30)
    citizen_email: EmailStr | None = None
    governorate: str = Field(min_length=2, max_length=60)
    title: str = Field(min_length=3, max_length=200)
    # 600 characters is the limit the submit form counts down from.
    description: str = Field(min_length=10, max_length=600)
    # Left unset, these are inferred by the triage engine.
    type: ComplaintType | None = None
    priority: Priority | None = None

    @field_validator("citizen_phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        cleaned = v.strip()
        if not all(ch.isdigit() or ch in "+-() " for ch in cleaned):
            raise ValueError("رقم الهاتف غير صالح / invalid phone number")
        return cleaned


class ComplaintUpdate(BaseModel):
    """Every field optional — a PATCH only touches what it names."""

    status: Status | None = None
    priority: Priority | None = None
    type: ComplaintType | None = None
    department_code: str | None = None
    assignee: str | None = Field(default=None, max_length=120)
    resolution: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=1000)
    actor: str = Field(default="موظف", max_length=120)


class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str | None
    size: int
    created_at: datetime
    url: str


class EventOut(BaseModel):
    id: int
    action: str
    field: str | None
    old_value: str | None
    new_value: str | None
    note: str | None
    actor: str
    created_at: datetime


class DepartmentOut(BaseModel):
    id: int
    code: str
    name_ar: str
    name_en: str


class ComplaintOut(BaseModel):
    id: int
    reference_no: str
    citizen_name: str
    citizen_phone: str
    citizen_email: str | None
    governorate: str
    title: str
    description: str
    type: ComplaintType
    priority: Priority
    status: Status
    department: DepartmentOut | None
    assignee: str | None
    resolution: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    closed_at: datetime | None
    attachments: list[AttachmentOut] = []
    events: list[EventOut] = []


class ComplaintSummary(BaseModel):
    """Lighter row for list views — no description, history or attachments."""

    id: int
    reference_no: str
    citizen_name: str
    title: str
    type: ComplaintType
    priority: Priority
    status: Status
    department: DepartmentOut | None
    assignee: str | None
    attachment_count: int
    created_at: datetime
    updated_at: datetime


class PagedComplaints(BaseModel):
    items: list[ComplaintSummary]
    total: int
    page: int
    per_page: int
    pages: int


class DuplicateHint(BaseModel):
    reference_no: str
    title: str
    similarity: float
    status: Status


class ComplaintCreated(BaseModel):
    """Creation echoes back how the complaint was triaged, plus any duplicates."""

    complaint: ComplaintOut
    auto_classified: bool
    confidence: float
    possible_duplicates: list[DuplicateHint] = []


class TrackingOut(BaseModel):
    """Public tracking view — no citizen contact details exposed."""

    reference_no: str
    title: str
    type: ComplaintType
    status: Status
    priority: Priority
    department: DepartmentOut | None
    resolution: str | None
    created_at: datetime
    updated_at: datetime
    events: list[EventOut]


class Stats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    by_priority: dict[str, int]
    by_department: dict[str, int]
    departments: list[dict]
    open_count: int
    resolved_count: int
    avg_resolution_hours: float | None
    new_today: int
    new_yesterday: int
    in_progress_count: int
    overdue_count: int
    resolved_this_week: int
    sla: dict
    status_breakdown: list[dict]
    type_breakdown: list[dict]
    recent_days: list[dict]
