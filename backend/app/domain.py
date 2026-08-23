"""Domain vocabulary: statuses, types, priorities, departments and routing rules.

The Arabic labels here are the ones the UI renders, so this file is the single
source of truth for both the API and the screens.
"""

from enum import Enum


class Status(str, Enum):
    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ComplaintType(str, Enum):
    INTERNET_OUTAGE = "internet_outage"
    SLOW_SPEED = "slow_speed"
    BILLING = "billing"
    LANDLINE = "landline"
    DIGITAL_SERVICES = "digital_services"
    INQUIRY = "inquiry"


# The workflow the dashboard advances a complaint through, in order.
FLOW: list[Status] = [
    Status.NEW,
    Status.ASSIGNED,
    Status.IN_PROGRESS,
    Status.RESOLVED,
    Status.CLOSED,
]

# Only these transitions are accepted; anything else is a 400.
ALLOWED_TRANSITIONS: dict[Status, set[Status]] = {
    Status.NEW: {Status.ASSIGNED, Status.IN_PROGRESS, Status.CLOSED},
    Status.ASSIGNED: {Status.IN_PROGRESS, Status.RESOLVED, Status.CLOSED},
    Status.IN_PROGRESS: {Status.RESOLVED, Status.ASSIGNED, Status.CLOSED},
    Status.RESOLVED: {Status.CLOSED, Status.IN_PROGRESS},
    Status.CLOSED: set(),
}

# Seeded on first run. `code` is the stable key the routing table points at.
DEPARTMENTS: list[dict] = [
    {"code": "syrian_telecom", "name_ar": "الشركة السورية للاتصالات",
     "name_en": "Syrian Telecommunications Company"},
    {"code": "service_quality", "name_ar": "دائرة جودة الخدمة",
     "name_en": "Service Quality Directorate"},
    {"code": "finance", "name_ar": "الدائرة المالية",
     "name_en": "Finance Directorate"},
    {"code": "fixed_networks", "name_ar": "دائرة الشبكات الثابتة",
     "name_en": "Fixed Networks Directorate"},
    {"code": "e_government", "name_ar": "الحكومة الإلكترونية",
     "name_en": "E-Government Directorate"},
    {"code": "citizen_service", "name_ar": "مكتب خدمة المواطن",
     "name_en": "Citizen Service Office"},
]

# Which department owns which complaint type.
ROUTING: dict[ComplaintType, str] = {
    ComplaintType.INTERNET_OUTAGE: "syrian_telecom",
    ComplaintType.SLOW_SPEED: "service_quality",
    ComplaintType.BILLING: "finance",
    ComplaintType.LANDLINE: "fixed_networks",
    ComplaintType.DIGITAL_SERVICES: "e_government",
    ComplaintType.INQUIRY: "citizen_service",
}

# The card code shown on the home page for each type.
TYPE_CODES: dict[ComplaintType, str] = {
    ComplaintType.INTERNET_OUTAGE: "C-01",
    ComplaintType.SLOW_SPEED: "C-02",
    ComplaintType.BILLING: "C-03",
    ComplaintType.LANDLINE: "C-04",
    ComplaintType.DIGITAL_SERVICES: "C-05",
    ComplaintType.INQUIRY: "C-06",
}

# The one-line description under each category card.
TYPE_DESCRIPTIONS: dict[ComplaintType, str] = {
    ComplaintType.INTERNET_OUTAGE: "انقطاع كامل أو متكرر للخدمة في منطقة أو خط محدد.",
    ComplaintType.SLOW_SPEED: "سرعة أقل من المتعاقد عليها أو تذبذب في الاتصال.",
    ComplaintType.BILLING: "فاتورة غير صحيحة، خصم مبالغ، أو مشكلة في الدفع.",
    ComplaintType.LANDLINE: "خط معطّل، تشويش، أو طلب نقل خط.",
    ComplaintType.DIGITAL_SERVICES: "مشكلة في منصة أو تطبيق حكومي إلكتروني.",
    ComplaintType.INQUIRY: "سؤال عن خدمة أو مقترح لتحسين الخدمات.",
}

# Hours a complaint of each priority is expected to be resolved within. Drives
# the "الالتزام بالمهلة" bar and the overdue KPI on the dashboard.
SLA_HOURS: dict[Priority, int] = {
    Priority.HIGH: 24,
    Priority.MEDIUM: 72,
    Priority.LOW: 120,
}

# Above this share of the SLA window a complaint counts as "قاربت المهلة".
SLA_WARNING_RATIO = 0.75

GOVERNORATES: list[str] = [
    "دمشق", "ريف دمشق", "حلب", "حمص", "حماة", "اللاذقية", "طرطوس",
    "دير الزور", "الحسكة", "إدلب", "درعا", "السويداء", "القنيطرة", "الرقة",
]

# Arabic + English labels the frontend renders. Kept server-side so the API and
# the UI can never drift apart.
LABELS: dict[str, dict[str, dict[str, str]]] = {
    "status": {
        Status.NEW: {"ar": "جديدة", "en": "New"},
        Status.ASSIGNED: {"ar": "محوّلة", "en": "Assigned"},
        Status.IN_PROGRESS: {"ar": "قيد المعالجة", "en": "In Progress"},
        Status.RESOLVED: {"ar": "تم الحل", "en": "Resolved"},
        Status.CLOSED: {"ar": "مغلقة", "en": "Closed"},
    },
    "priority": {
        Priority.LOW: {"ar": "منخفضة", "en": "Low"},
        Priority.MEDIUM: {"ar": "متوسطة", "en": "Medium"},
        Priority.HIGH: {"ar": "عالية", "en": "High"},
    },
    "type": {
        ComplaintType.INTERNET_OUTAGE: {
            "ar": "انقطاع خدمة الإنترنت", "en": "Internet Outage"},
        ComplaintType.SLOW_SPEED: {
            "ar": "بطء السرعة وجودة الخدمة", "en": "Speed and Service Quality"},
        ComplaintType.BILLING: {
            "ar": "الفواتير والرصيد", "en": "Billing and Balance"},
        ComplaintType.LANDLINE: {
            "ar": "الهاتف الأرضي", "en": "Landline"},
        ComplaintType.DIGITAL_SERVICES: {
            "ar": "الخدمات الحكومية الرقمية", "en": "Government Digital Services"},
        ComplaintType.INQUIRY: {
            "ar": "استفسار أو مقترح", "en": "Inquiry or Suggestion"},
    },
}

# Palette the dashboard charts draw with, in the order the design lists them.
STATUS_COLORS: dict[Status, str] = {
    Status.NEW: "#054239",
    Status.ASSIGNED: "#0d6a5c",
    Status.IN_PROGRESS: "#428177",
    Status.RESOLVED: "#988561",
    Status.CLOSED: "#cbcbcb",
}

TYPE_COLORS: dict[ComplaintType, str] = {
    ComplaintType.INTERNET_OUTAGE: "#054239",
    ComplaintType.SLOW_SPEED: "#0d6a5c",
    ComplaintType.BILLING: "#428177",
    ComplaintType.LANDLINE: "#988561",
    ComplaintType.DIGITAL_SERVICES: "#b9a779",
    ComplaintType.INQUIRY: "#cfc4a3",
}
