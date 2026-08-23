"""Populate the database with realistic sample complaints for demos and testing.

Run:  python seed.py         (adds samples)
      python seed.py --reset (wipes complaints first)
"""

import random
import sys
from datetime import datetime, timedelta, timezone

from app import repository as repo, services
from app.db import get_db, init_db
from app.domain import GOVERNORATES, Priority, Status
from app.schemas import ComplaintCreate, ComplaintUpdate

SAMPLES = [
    ("انقطاع الإنترنت في حي المزة منذ ثلاثة أيام",
     "انقطاع كامل لخدمة ADSL عن كامل البناء منذ ٢٠ آب، مع استمرار عمل الخط الأرضي. تم توثيق شكاوى مشابهة من نفس المقسم."),
    ("فاتورة إنترنت مضاعفة لشهر تموز",
     "قيمة الفاتورة بلغت ضعف المعتاد دون تغيير الباقة، وأطلب مراجعة الحساب واسترداد الفرق."),
    ("بطء شديد في السرعة أوقات المساء",
     "انخفاض السرعة إلى أقل من ٢ ميغابت بين الثامنة والحادية عشرة مساءً بشكل يومي."),
    ("تعذّر إتمام الدفع في المنصة الحكومية",
     "تظهر رسالة خطأ عند تأكيد الدفع الإلكتروني في البوابة، مع خصم المبلغ من الحساب."),
    ("طلب نقل خط أرضي إلى عنوان جديد",
     "أرغب بنقل الخط الأرضي إلى عنوان سكني جديد ضمن نفس المدينة، وأستفسر عن الإجراءات."),
    ("تشويش على الخط الأرضي في الحسكة",
     "يوجد تشويش دائم على الهاتف الأرضي منذ أسبوعين ولا تُسمع المكالمة بوضوح."),
    ("مقترح: إضافة خدمة تتبع الشكوى عبر الرسائل",
     "أقترح تمكين تتبع حالة الشكوى عبر رسالة قصيرة بالرقم المرجعي بدل الدخول إلى الموقع."),
    ("انقطاع متكرر للخدمة في حي الميدان",
     "الخدمة تنقطع بشكل متكرر يومياً لساعات، وقدمت شكوى سابقة ولم يتم الرد عليها."),
    ("تذبذب في جودة الاتصال",
     "تذبذب مستمر في سرعة الإنترنت وتقطع أثناء الاجتماعات، والسرعة أقل من المتعاقد عليها."),
    ("خصم مبلغ غير مبرر من الرصيد",
     "تم خصم مبلغ من رصيدي دون أي اشتراك أو خدمة إضافية، وأطلب توضيح سبب الخصم."),
    ("استفسار عن باقات الإنترنت المنزلي",
     "أرغب بالاستفسار عن الباقات المتوفرة للإنترنت المنزلي وأسعارها وكيفية تغيير الباقة الحالية."),
    ("لا يمكن تسجيل الدخول إلى البوابة الإلكترونية",
     "أدخل كلمة المرور الصحيحة لكن الموقع يرفض تسجيل الدخول ويعطي خطأ في كل محاولة."),
    ("انقطاع كامل للخدمة في منطقة صناعية",
     "انقطاع تام للإنترنت منذ أربعة أيام، والأمر طارئ لتوقف العمل في عدة منشآت."),
    ("سرعة أقل من المتعاقد عليها",
     "السرعة المقاسة لا تتجاوز نصف السرعة المتعاقد عليها في جميع الأوقات."),
    ("Slow internet speed on fiber package",
     "My internet has been extremely slow all week despite paying for a premium fiber package."),
]

NAMES = [
    "أحمد الخطيب", "فاطمة العلي", "محمد حسن", "ليلى إبراهيم", "عمر السيد",
    "نور الدين قاسم", "رنا الشامي", "سامر يوسف", "هدى المصري", "خالد العمر",
]
STAFF = [
    "م. رنا عبدو", "أ. لؤي حسن", "م. هبة الشيخ", "أ. مازن كريم",
    "أ. نور العلي", "أ. سلمى ديب",
]

NOTES = {
    Status.ASSIGNED: "تم تعيين مسؤول لمتابعة الشكوى.",
    Status.IN_PROGRESS: "تم إحالة الشكوى إلى فريق الصيانة الميداني.",
    Status.RESOLVED: "تمت معالجة المشكلة والتحقق من عودة الخدمة.",
    Status.CLOSED: "تم إغلاق الشكوى بعد تأكيد المواطن.",
}


def reset() -> None:
    with get_db(write=True) as conn:
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM attachments")
        conn.execute("DELETE FROM complaints")
    print("cleared existing complaints")


def seed() -> None:
    random.seed(7)
    ages = _spread_ages(len(SAMPLES))
    created: list[tuple[int, float]] = []

    with get_db(write=True) as conn:
        for i, (title, description) in enumerate(SAMPLES):
            payload = ComplaintCreate(
                citizen_name=random.choice(NAMES),
                citizen_phone=f"09{random.randint(10000000, 99999999)}",
                citizen_email=f"citizen{i}@example.sy",
                governorate=random.choice(GOVERNORATES),
                title=title,
                description=description,
            )
            complaint = services.create_complaint(conn, payload, files=None)["complaint"]
            _backdate(conn, complaint["id"], ages[i])
            created.append((complaint["id"], ages[i]))

    # Older complaints have had time to be worked and closed; recent ones are
    # still moving. That keeps the SLA bars and the trend chart believable, and
    # leaves every one of the five statuses represented on the dashboard.
    with get_db(write=True) as conn:
        for complaint_id, age_days in created:
            if age_days < 0.6:
                continue  # arrived today, still 'جديدة' awaiting pickup
            _advance(conn, complaint_id, Status.ASSIGNED, age_days)
            if age_days < 1.5:
                continue
            _advance(conn, complaint_id, Status.IN_PROGRESS, age_days)
            if age_days < 3:
                continue
            _advance(conn, complaint_id, Status.RESOLVED, age_days)
            if age_days > 7:
                _advance(conn, complaint_id, Status.CLOSED, age_days)

    with get_db(write=True) as conn:
        total = conn.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    print(f"seeded {len(created)} complaints (database now holds {total})")


def _spread_ages(count: int) -> list[float]:
    """Ages in days, spread across the dashboard's 14-day window."""
    return [round(random.uniform(0, 13.5), 2) for _ in range(count)]


def _backdate(conn, complaint_id: int, age_days: float) -> None:
    stamp = _stamp(age_days)
    conn.execute(
        "UPDATE complaints SET created_at = ?, updated_at = ? WHERE id = ?",
        (stamp, stamp, complaint_id),
    )
    conn.execute(
        "UPDATE events SET created_at = ? WHERE complaint_id = ?", (stamp, complaint_id)
    )


def _stamp(age_days: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=age_days)
    ).isoformat(timespec="seconds")


# Hours after submission that each workflow step happened. Resolution lands
# inside the SLA window for most complaints, so the compliance bar is realistic.
STEP_HOURS = {
    Status.ASSIGNED: (1, 3),
    Status.IN_PROGRESS: (2, 6),
    Status.RESOLVED: (6, 20),
    Status.CLOSED: (22, 30),
}


def _advance(conn, complaint_id: int, status: Status, age_days: float) -> None:
    """Move one step forward and timestamp it a few hours after submission."""
    complaint = repo.get_complaint(conn, complaint_id)
    services.apply_update(
        conn,
        complaint,
        ComplaintUpdate(
            status=status,
            assignee=random.choice(STAFF),
            actor=random.choice(STAFF),
            note=NOTES[status],
            resolution=(
                "تم إصلاح العطل واستعادة الخدمة بالكامل."
                if status is Status.RESOLVED else None
            ),
            priority=random.choice(list(Priority)) if random.random() < 0.3 else None,
        ),
    )
    elapsed_days = random.uniform(*STEP_HOURS[status]) / 24
    stamp = _stamp(max(age_days - elapsed_days, 0))
    conn.execute(
        "UPDATE complaints SET updated_at = ?,"
        " resolved_at = CASE WHEN resolved_at IS NULL THEN NULL ELSE ? END,"
        " closed_at = CASE WHEN closed_at IS NULL THEN NULL ELSE ? END"
        " WHERE id = ?",
        (stamp, stamp, stamp, complaint_id),
    )
    conn.execute(
        "UPDATE events SET created_at = ? WHERE id ="
        " (SELECT MAX(id) FROM events WHERE complaint_id = ?)",
        (stamp, complaint_id),
    )


if __name__ == "__main__":
    init_db()
    if "--reset" in sys.argv:
        reset()
    seed()
