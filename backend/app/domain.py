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
    # Telecommunications
    INTERNET_OUTAGE = "internet_outage"
    SERVICE_QUALITY = "service_quality"
    NETWORK_INFRASTRUCTURE = "network_infrastructure"
    # Operators and ministry affiliates, i.e. services delivered to citizens
    LANDLINE = "landline"
    BILLING = "billing"
    INQUIRY = "inquiry"
    # Informatics and e-government
    GOV_PLATFORMS = "gov_platforms"
    E_SERVICES = "e_services"
    # Digital transformation
    SERVICE_DIGITIZATION = "service_digitization"
    # Information technology
    GOV_SYSTEMS = "gov_systems"
    # Cybersecurity
    CYBERSECURITY = "cybersecurity"
    # Data and digital statistics
    DATA_STATISTICS = "data_statistics"


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

# The entities that actually receive complaints, with the problem domain each
# one owns. Seeded on first run; `code` is the stable key routing points at.
DEPARTMENTS: list[dict] = [
    {"code": "digital_transformation",
     "name_ar": "مديرية التحول الرقمي",
     "name_en": "Digital Transformation Directorate",
     "scope_ar": "رقمنة الخدمات الحكومية، أتمتة المعاملات، وربط الجهات الحكومية."},
    {"code": "information_technology",
     "name_ar": "مديرية تقانة المعلومات",
     "name_en": "Information Technology Directorate",
     "scope_ar": "الأنظمة الحكومية، قواعد البيانات، والتكامل بين الأنظمة."},
    {"code": "telecommunications",
     "name_ar": "مديرية الاتصالات",
     "name_en": "Telecommunications Directorate",
     "scope_ar": "مشاكل الاتصالات، جودة الخدمة، البنية التحتية، وتغطية الشبكات."},
    {"code": "e_government",
     "name_ar": "مديرية المعلوماتية والحكومة الإلكترونية",
     "name_en": "Informatics and E-Government Directorate",
     "scope_ar": "تطوير البوابات والمنصات الحكومية والخدمات الإلكترونية."},
    {"code": "cybersecurity",
     "name_ar": "الجهات المعنية بالأمن السيبراني",
     "name_en": "Cybersecurity Authorities",
     "scope_ar": "حماية البيانات والأنظمة الحكومية، واكتشاف التهديدات."},
    {"code": "data_statistics",
     "name_ar": "الجهات المعنية بالبيانات والإحصاء الرقمي",
     "name_en": "Digital Data and Statistics Authorities",
     "scope_ar": "جمع البيانات، تحليلها، ولوحات المعلومات لدعم القرار."},
    {"code": "affiliated_operators",
     "name_ar": "الجهات التابعة للوزارة ومؤسسات الاتصالات",
     "name_en": "Ministry Affiliates and Telecom Operators",
     "scope_ar": "الخدمات المقدَّمة مباشرة للمواطنين."},
]

# Which department owns which complaint type. Every department above appears
# here at least once — a department nothing routes to would never receive work.
ROUTING: dict[ComplaintType, str] = {
    ComplaintType.INTERNET_OUTAGE: "telecommunications",
    ComplaintType.SERVICE_QUALITY: "telecommunications",
    ComplaintType.NETWORK_INFRASTRUCTURE: "telecommunications",
    ComplaintType.LANDLINE: "affiliated_operators",
    ComplaintType.BILLING: "affiliated_operators",
    ComplaintType.INQUIRY: "affiliated_operators",
    ComplaintType.GOV_PLATFORMS: "e_government",
    ComplaintType.E_SERVICES: "e_government",
    ComplaintType.SERVICE_DIGITIZATION: "digital_transformation",
    ComplaintType.GOV_SYSTEMS: "information_technology",
    ComplaintType.CYBERSECURITY: "cybersecurity",
    ComplaintType.DATA_STATISTICS: "data_statistics",
}

# The card code shown on the home page for each type.
TYPE_CODES: dict[ComplaintType, str] = {
    ComplaintType.INTERNET_OUTAGE: "C-01",
    ComplaintType.SERVICE_QUALITY: "C-02",
    ComplaintType.NETWORK_INFRASTRUCTURE: "C-03",
    ComplaintType.LANDLINE: "C-04",
    ComplaintType.BILLING: "C-05",
    ComplaintType.INQUIRY: "C-06",
    ComplaintType.GOV_PLATFORMS: "C-07",
    ComplaintType.E_SERVICES: "C-08",
    ComplaintType.SERVICE_DIGITIZATION: "C-09",
    ComplaintType.GOV_SYSTEMS: "C-10",
    ComplaintType.CYBERSECURITY: "C-11",
    ComplaintType.DATA_STATISTICS: "C-12",
}

# The one-line description under each category card.
TYPE_DESCRIPTIONS: dict[ComplaintType, str] = {
    ComplaintType.INTERNET_OUTAGE:
        "انقطاع كامل أو متكرر للخدمة في منطقة أو خط محدد.",
    ComplaintType.SERVICE_QUALITY:
        "سرعة أقل من المتعاقد عليها أو تذبذب في جودة الاتصال.",
    ComplaintType.NETWORK_INFRASTRUCTURE:
        "ضعف التغطية، أو أعمال الشبكات والأبراج والكابلات.",
    ComplaintType.LANDLINE:
        "خط معطّل، تشويش، أو طلب نقل خط.",
    ComplaintType.BILLING:
        "فاتورة غير صحيحة، خصم مبالغ، أو مشكلة في الدفع.",
    ComplaintType.INQUIRY:
        "سؤال عن خدمة أو مقترح لتحسين الخدمات.",
    ComplaintType.GOV_PLATFORMS:
        "عطل أو صعوبة في استخدام بوابة أو منصة حكومية.",
    ComplaintType.E_SERVICES:
        "تعذّر إنجاز معاملة إلكترونية أو الحصول على خدمة رقمية.",
    ComplaintType.SERVICE_DIGITIZATION:
        "معاملة ما تزال ورقية، أو ضعف الربط بين الجهات الحكومية.",
    ComplaintType.GOV_SYSTEMS:
        "خلل في نظام حكومي أو قاعدة بيانات أو التكامل بينها.",
    ComplaintType.CYBERSECURITY:
        "تسريب بيانات، اشتباه اختراق، أو ثغرة أمنية.",
    ComplaintType.DATA_STATISTICS:
        "بيانات غير دقيقة أو ناقصة في المؤشرات ولوحات المعلومات.",
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


def escalate_priority(hours_open: float, current: Priority) -> Priority:
    """The priority an open complaint should carry, given how long it has waited.

    Reuses SLA_HOURS instead of a second set of magic numbers: waiting longer
    than the Medium SLA already justifies High, and waiting longer than the
    High SLA — the tightest window there is — justifies moving Low to Medium
    even though it hasn't technically blown its own, much longer, deadline.
    Never used to lower a priority a human deliberately raised.
    """
    if current is Priority.HIGH:
        return current
    if hours_open >= SLA_HOURS[Priority.MEDIUM]:
        return Priority.HIGH
    if hours_open >= SLA_HOURS[Priority.HIGH] and current is Priority.LOW:
        return Priority.MEDIUM
    return current

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
        ComplaintType.SERVICE_QUALITY: {
            "ar": "بطء السرعة وجودة الخدمة", "en": "Speed and Service Quality"},
        ComplaintType.NETWORK_INFRASTRUCTURE: {
            "ar": "البنية التحتية وتغطية الشبكات",
            "en": "Infrastructure and Network Coverage"},
        ComplaintType.LANDLINE: {
            "ar": "الهاتف الأرضي", "en": "Landline"},
        ComplaintType.BILLING: {
            "ar": "الفواتير والرصيد", "en": "Billing and Balance"},
        ComplaintType.INQUIRY: {
            "ar": "استفسار أو مقترح", "en": "Inquiry or Suggestion"},
        ComplaintType.GOV_PLATFORMS: {
            "ar": "البوابات والمنصات الحكومية",
            "en": "Government Portals and Platforms"},
        ComplaintType.E_SERVICES: {
            "ar": "الخدمات الإلكترونية للمواطن", "en": "Citizen E-Services"},
        ComplaintType.SERVICE_DIGITIZATION: {
            "ar": "رقمنة وأتمتة المعاملات",
            "en": "Service Digitization and Automation"},
        ComplaintType.GOV_SYSTEMS: {
            "ar": "الأنظمة وقواعد البيانات", "en": "Systems and Databases"},
        ComplaintType.CYBERSECURITY: {
            "ar": "الأمن السيبراني وحماية البيانات",
            "en": "Cybersecurity and Data Protection"},
        ComplaintType.DATA_STATISTICS: {
            "ar": "البيانات والإحصاء الرقمي", "en": "Data and Digital Statistics"},
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

# A single ramp from the darkest forest to the lightest sand, extending the
# design's original six-step chart palette to cover twelve categories while
# staying inside the same two brand families.
TYPE_COLORS: dict[ComplaintType, str] = {
    ComplaintType.INTERNET_OUTAGE: "#054239",
    ComplaintType.SERVICE_QUALITY: "#0a5449",
    ComplaintType.NETWORK_INFRASTRUCTURE: "#0d6a5c",
    ComplaintType.LANDLINE: "#2b7a6c",
    ComplaintType.BILLING: "#428177",
    ComplaintType.INQUIRY: "#5c9689",
    ComplaintType.GOV_PLATFORMS: "#7d6a3c",
    ComplaintType.E_SERVICES: "#988561",
    ComplaintType.SERVICE_DIGITIZATION: "#a89468",
    ComplaintType.GOV_SYSTEMS: "#b9a779",
    ComplaintType.CYBERSECURITY: "#c8bb95",
    ComplaintType.DATA_STATISTICS: "#cfc4a3",
}
