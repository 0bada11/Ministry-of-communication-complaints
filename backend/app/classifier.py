"""Rule-based triage: infer type, priority and duplicates from complaint text.

Deterministic keyword scoring in Arabic and English — no network call, no model
to host, and every decision is explainable back to the citizen.
"""

import re
import unicodedata
from difflib import SequenceMatcher

from .domain import ROUTING, ComplaintType, Priority

# Arabic diacritics and tatweel, stripped before matching.
_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")

TYPE_KEYWORDS: dict[ComplaintType, tuple[str, ...]] = {
    ComplaintType.INTERNET_OUTAGE: (
        "انقطاع", "مقطوع", "لا يوجد انترنت", "توقف الانترنت", "الخدمة متوقفة",
        "منقطع", "بدون انترنت", "الانترنت لا يعمل", "adsl", "فايبر", "الياف",
        "outage", "no internet", "disconnected", "service down", "cut off",
    ),
    ComplaintType.SERVICE_QUALITY: (
        "بطء", "بطيء", "سرعة", "تذبذب", "جودة الخدمة", "تقطع",
        "اقل من المتعاقد", "باقة", "تحميل بطيء", "ping",
        "slow", "speed", "bandwidth", "latency", "quality", "unstable", "lag",
    ),
    ComplaintType.NETWORK_INFRASTRUCTURE: (
        "تغطية", "ضعف الاشارة", "الاشارة ضعيفة", "برج", "ابراج", "كابل", "كبل",
        "عمود", "مقسم", "بنية تحتية", "شبكة المنطقة", "توسعة الشبكة",
        "لا توجد تغطية", "صيانة الشبكة",
        "coverage", "signal", "tower", "cable", "infrastructure", "network build",
    ),
    ComplaintType.LANDLINE: (
        "ارضي", "خط ثابت", "هاتف ثابت", "سنترال", "تشويش", "نقل خط", "الخط معطل",
        "نغمة", "الشبكة الثابتة",
        "landline", "fixed line", "telephone line", "dial tone", "noise",
    ),
    ComplaintType.BILLING: (
        "فاتورة", "فواتير", "رصيد", "دفع", "خصم", "مبلغ", "رسوم", "اشتراك",
        "استرداد", "تسعيرة", "محاسبة", "سعر", "مضاعفة",
        "bill", "billing", "payment", "charge", "refund", "invoice", "fee",
        "balance", "price",
    ),
    ComplaintType.INQUIRY: (
        "استفسار", "سؤال", "استعلام", "اقتراح", "مقترح", "اقترح", "كيف", "متى",
        "هل يمكن", "ما هي", "تحسين", "فكرة",
        "inquiry", "question", "suggestion", "suggest", "proposal", "idea",
        "how do i", "when will", "what is",
    ),
    ComplaintType.GOV_PLATFORMS: (
        "منصة", "بوابة", "الموقع الحكومي", "تطبيق حكومي", "الحكومة الالكترونية",
        "تسجيل الدخول", "كلمة المرور", "الحساب لا يعمل", "الصفحة لا تفتح",
        "استمارة الكترونية", "المنصة معطلة",
        "platform", "portal", "government website", "government app", "login",
        "password", "e-government",
    ),
    ComplaintType.E_SERVICES: (
        "خدمة الكترونية", "معامله الكترونيه", "الدفع الالكتروني", "طلب الكتروني",
        "تعذر اتمام", "لم تكتمل المعامله", "شهادة الكترونية", "حجز موعد",
        "وثيقة الكترونية", "تصديق",
        "online service", "e-service", "online payment", "online request",
        "appointment", "certificate",
    ),
    ComplaintType.SERVICE_DIGITIZATION: (
        "رقمنة", "اتمته", "اتمتة", "معامله ورقيه", "ورقي", "ما زالت ورقية",
        "ربط الجهات", "ربط المديريات", "تحول رقمي", "اجراءات يدويه",
        "مراجعة شخصية", "تبسيط الاجراءات",
        "digitization", "automation", "paper based", "manual process",
        "digital transformation",
    ),
    ComplaintType.GOV_SYSTEMS: (
        "نظام", "الانظمة", "قاعدة بيانات", "قواعد البيانات", "تكامل", "ربط الانظمة",
        "سجل غير محدث", "خطا في النظام", "تعطل النظام", "مزامنة", "بيانات غير متطابقة",
        "system", "database", "integration", "sync", "record mismatch",
    ),
    ComplaintType.CYBERSECURITY: (
        "اختراق", "تسريب", "ثغرة", "امن سيبراني", "امن المعلومات", "احتيال",
        "تصيد", "فيروس", "برمجيات خبيثة", "سرقة حساب", "بيانات مسربة",
        "هجوم", "نشاط مشبوه",
        "breach", "leak", "vulnerability", "cyber", "phishing", "malware",
        "hacked", "security incident", "suspicious",
    ),
    ComplaintType.DATA_STATISTICS: (
        "احصاء", "احصائيات", "بيانات غير دقيقه", "مؤشر", "مؤشرات", "لوحة معلومات",
        "تقرير احصائي", "ارقام غير صحيحه", "بيانات ناقصه", "تحليل البيانات",
        "statistics", "dashboard", "indicator", "inaccurate data",
        "missing data", "data analysis",
    ),
}

# Priority signals, strongest first. First matching tier wins.
PRIORITY_KEYWORDS: tuple[tuple[Priority, tuple[str, ...]], ...] = (
    (
        Priority.HIGH,
        (
            "انقطاع كامل", "توقف تام", "طارئ", "عاجل", "خطر", "مستشفى", "اسعاف",
            "طوارئ", "كارثة", "منذ ايام", "منذ اسبوع", "متكرر", "مرارا",
            "لا يعمل", "معطل", "لم يتم الرد", "تجاهل", "شكوى سابقة", "خسارة",
            "urgent", "emergency", "critical", "complete outage", "hospital",
            "repeated", "not working", "broken", "no response", "escalate",
        ),
    ),
    (
        Priority.LOW,
        (
            "استفسار", "سؤال", "اقتراح", "مقترح", "معلومة", "بسيط", "طلب نقل",
            "inquiry", "question", "suggestion", "minor", "info",
        ),
    ),
)


def normalize(text: str) -> str:
    """Lowercase, strip diacritics and unify Arabic letter variants."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = _DIACRITICS.sub("", text)
    for src, dst in (("أإآٱ", "ا"), ("ى", "ي"), ("ة", "ه"), ("ؤ", "و"), ("ئ", "ي")):
        for ch in src:
            text = text.replace(ch, dst)
    return re.sub(r"\s+", " ", text).strip()


def classify_type(text: str) -> tuple[ComplaintType, float]:
    """Pick the type whose keywords appear most often. Returns (type, confidence)."""
    haystack = normalize(text)
    scores = {
        ctype: sum(1 for kw in keywords if normalize(kw) in haystack)
        for ctype, keywords in TYPE_KEYWORDS.items()
    }
    best = max(scores, key=lambda t: scores[t])
    total = sum(scores.values())
    if scores[best] == 0:
        # Nothing matched — an unclassifiable message is a question for the
        # citizen service office rather than a technical fault.
        return ComplaintType.INQUIRY, 0.0
    return best, round(scores[best] / total, 2)


def suggest_priority(text: str, ctype: ComplaintType) -> Priority:
    """First matching keyword tier wins; otherwise fall back on the type."""
    haystack = normalize(text)
    for priority, keywords in PRIORITY_KEYWORDS:
        if any(normalize(kw) in haystack for kw in keywords):
            return priority
    if ctype is ComplaintType.INQUIRY:
        return Priority.LOW
    if ctype in (ComplaintType.INTERNET_OUTAGE, ComplaintType.CYBERSECURITY):
        return Priority.HIGH
    return Priority.MEDIUM


def route(ctype: ComplaintType) -> str:
    """Department code responsible for this complaint type."""
    return ROUTING.get(ctype, "affiliated_operators")


def similarity(a: str, b: str) -> float:
    """0..1 text similarity used for duplicate detection."""
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def triage(title: str, description: str) -> dict:
    """Full triage pass over a freshly submitted complaint."""
    text = f"{title} {description}"
    ctype, confidence = classify_type(text)
    return {
        "type": ctype,
        "confidence": confidence,
        "priority": suggest_priority(text, ctype),
        "department_code": route(ctype),
    }
