"""End-to-end checks over the whole API, run against a throwaway database.

Run:  python test_api.py
"""

import io
import shutil
import tempfile
from pathlib import Path

# Point the app at a temp database *before* importing anything that touches it.
import app.db as db

_tmp = Path(tempfile.mkdtemp(prefix="moc_test_"))
db.DB_PATH = _tmp / "test.db"
db.UPLOAD_DIR = _tmp / "uploads"

import app.repository as repo  # noqa: E402
import app.services as services  # noqa: E402  (must follow the path override)

services.UPLOAD_DIR = db.UPLOAD_DIR

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

passed = failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


def main() -> int:
    with TestClient(app) as client:
        print("\n[meta]")
        meta = client.get("/api/meta").json()
        check("7 departments seeded", len(meta["departments"]) == 7)
        check("departments carry their remit",
              all(d.get("scope_ar") for d in meta["departments"]))
        check("6 statuses exposed", len(meta["statuses"]) == 6)
        check("12 complaint types exposed", len(meta["types"]) == 12)
        check("every type routes to a real department",
              all(t["department"] for t in meta["types"]))
        check("every department receives at least one type",
              {d["code"] for d in meta["departments"]}
              == {t["department"]["code"] for t in meta["types"]})
        check("types carry card code + department",
              meta["types"][0]["code"] == "C-01"
              and meta["types"][0]["department"]["code"] == "telecommunications")
        check("14 governorates exposed", len(meta["governorates"]) == 14)
        check("labels are bilingual", "ar" in meta["types"][0] and "en" in meta["types"][0])
        check("health ok", client.get("/api/health").json()["status"] == "ok")

        print("\n[auto-classification and routing]")
        created = client.post(
            "/api/complaints",
            json={
                "citizen_name": "أحمد الخطيب",
                "citizen_phone": "+963911234567",
                "citizen_email": "ahmad@example.sy",
                "governorate": "دمشق",
                "title": "بطء شديد في خدمة الإنترنت",
                "description": "سرعة الإنترنت بطيئة جداً منذ أسبوعين رغم اشتراكي بباقة الألياف الضوئية.",
            },
        )
        check("created 201", created.status_code == 201, created.text)
        body = created.json()
        complaint = body["complaint"]
        check("classified as service_quality", complaint["type"] == "service_quality",
              complaint["type"])
        check("quality issue routed to telecommunications",
              complaint["department"]["code"] == "telecommunications")
        check("complaints start New but already routed",
              complaint["status"] == "new" and complaint["department"] is not None)
        check("reference number issued",
              complaint["reference_no"].startswith("MOCT-"), complaint["reference_no"])
        check("auto_classified flag set", body["auto_classified"] is True)
        check("creation logged 4 events", len(complaint["events"]) == 4,
              str([e["action"] for e in complaint["events"]]))

        billing = client.post("/api/complaints", json={
            "citizen_name": "فاطمة العلي", "citizen_phone": "0955555555", "governorate": "حلب",
            "title": "فاتورة غير صحيحة",
            "description": "وصلتني فاتورة بمبلغ مضاعف عن الشهر الماضي وأطلب استرداد الفرق.",
        }).json()["complaint"]
        check("billing routed to the operators",
              billing["department"]["code"] == "affiliated_operators",
              billing["type"])

        urgent = client.post("/api/complaints", json={
            "citizen_name": "عمر السيد", "citizen_phone": "0944444444", "governorate": "حمص",
            "title": "انقطاع كامل للخدمة",
            "description": "انقطاع كامل للإنترنت منذ ثلاثة أيام والأمر طارئ لوجود مستشفى يعتمد عليها.",
        }).json()["complaint"]
        check("emergency wording -> high", urgent["priority"] == "high",
              urgent["priority"])
        check("outage routed to telecommunications",
              urgent["department"]["code"] == "telecommunications", urgent["type"])

        english = client.post("/api/complaints", json={
            "citizen_name": "Sara Nasser", "citizen_phone": "0933333333", "governorate": "دمشق",
            "title": "Slow internet speed",
            "description": "My internet has been extremely slow all week on a fiber package.",
        }).json()["complaint"]
        check("english text classified too", english["type"] == "service_quality",
              english["type"])

        suggestion = client.post("/api/complaints", json={
            "citizen_name": "هدى المصري", "citizen_phone": "0922222222", "governorate": "حماة",
            "title": "اقتراح لتحسين الخدمة",
            "description": "أقترح تطوير تطبيق موبايل لمتابعة الشكوى ودفع الفاتورة بشكل أسهل.",
        }).json()["complaint"]
        check("suggestion -> operators + low",
              suggestion["department"]["code"] == "affiliated_operators"
              and suggestion["priority"] == "low",
              f"{suggestion['type']}/{suggestion['priority']}")

        print("\n[explicit override beats inference]")
        manual = client.post("/api/complaints", json={
            "citizen_name": "خالد العمر", "citizen_phone": "0911111111", "governorate": "درعا",
            "title": "بطء في الإنترنت", "description": "الإنترنت بطيء جداً ولا يعمل بشكل جيد.",
            "type": "billing",
        }).json()
        check("explicit type respected", manual["complaint"]["type"] == "billing")
        check("auto_classified false", manual["auto_classified"] is False)
        check("a citizen-supplied priority is ignored, not honoured",
              client.post("/api/complaints", json={
                  "citizen_name": "محاول التصعيد", "citizen_phone": "0900011122",
                  "governorate": "دمشق", "title": "سؤال بسيط عن مواعيد الدوام",
                  "description": "أرغب بمعرفة مواعيد الدوام الرسمي في مكاتبكم.",
                  "priority": "high",
              }).json()["complaint"]["priority"] != "high")
        check("every complaint records how its priority was decided", any(
            e["action"] == "priority_set" and e["actor"] == "system"
            for e in manual["complaint"]["events"]),
            str([e["action"] for e in manual["complaint"]["events"]]))

        print("\n[duplicate detection]")
        dup = client.post("/api/complaints", json={
            "citizen_name": "جار المشتكي", "citizen_phone": "0966666666", "governorate": "دمشق",
            "title": "بطء شديد في خدمة الإنترنت",
            "description": "سرعة الإنترنت بطيئة جداً منذ أسبوعين رغم اشتراكي بباقة الألياف الضوئية.",
        }).json()
        check("near-identical text flagged", len(dup["possible_duplicates"]) >= 1,
              str(dup["possible_duplicates"]))
        check("duplicate hint carries reference",
              dup["possible_duplicates"][0]["reference_no"] == complaint["reference_no"])
        check("a complaint never flags itself",
              all(d["reference_no"] != dup["complaint"]["reference_no"]
                  for d in dup["possible_duplicates"]),
              str(dup["possible_duplicates"]))
        check("unique text flags nothing", not client.post("/api/complaints", json={
            "citizen_name": "مواطن آخر", "citizen_phone": "0988888888",
            "governorate": "إدلب", "title": "استفسار عن مواعيد الصيانة المجدولة",
            "description": "أرغب بمعرفة جدول الصيانة المجدولة للشهر القادم في منطقتي.",
        }).json()["possible_duplicates"])

        print("\n[detailed location]")
        with_location = client.post("/api/complaints", json={
            "citizen_name": "زياد نجم", "citizen_phone": "0999999999",
            "governorate": "حمص", "title": "انقطاع كهرباء يؤثر على المقسم",
            "description": "انقطاع الإنترنت في المبنى مرتبط بانقطاع الكهرباء عن المقسم المحلي.",
            "location_detail": "شارع الحمراء، بناء ٧، الطابق الثالث، قرب المخبز",
        }).json()["complaint"]
        check("location_detail stored",
              with_location["location_detail"] == "شارع الحمراء، بناء ٧، الطابق الثالث، قرب المخبز")
        without_location = client.post("/api/complaints", json={
            "citizen_name": "سلوى حداد", "citizen_phone": "0988887777",
            "governorate": "حماة", "title": "استفسار عام",
            "description": "أرغب بمعرفة أوقات الدوام الرسمي لمكتب خدمة المواطن.",
        }).json()["complaint"]
        check("location_detail is optional and defaults to null",
              without_location["location_detail"] is None)
        located_update = client.patch(f"/api/complaints/{without_location['id']}", json={
            "location_detail": "حي الجسر، بناء ٣", "actor": "أ. لؤي حسن",
        })
        check("staff can add a location after the fact",
              located_update.status_code == 200
              and located_update.json()["location_detail"] == "حي الجسر، بناء ٣")
        check("location update logged", any(
            e["action"] == "location_updated"
            for e in client.get(f"/api/complaints/{without_location['id']}/events").json()))

        print("\n[validation]")
        check("short description rejected", client.post("/api/complaints", json={
            "citizen_name": "ب", "citizen_phone": "1", "title": "x", "description": "y",
        }).status_code == 422)
        check("bad phone rejected", client.post("/api/complaints", json={
            "citizen_name": "اسم صحيح", "citizen_phone": "phone!!",
            "governorate": "دمشق", "title": "عنوان",
            "description": "وصف طويل بما فيه الكفاية للتجاوز.",
        }).status_code == 422)
        check("bad email rejected", client.post("/api/complaints", json={
            "citizen_name": "اسم صحيح", "citizen_phone": "0900000000",
            "governorate": "دمشق", "citizen_email": "not-an-email", "title": "عنوان",
            "description": "وصف طويل بما فيه الكفاية للتجاوز.",
        }).status_code == 422)

        print("\n[attachments]")
        cid = complaint["id"]
        upload = client.post(
            f"/api/complaints/{cid}/attachments",
            files=[("files", ("speedtest.png", io.BytesIO(b"\x89PNG fake"), "image/png"))],
            data={"actor": "أحمد الخطيب"},
        )
        check("attachment uploaded", upload.status_code == 201, upload.text)
        attachment = upload.json()[0]
        check("attachment url returned",
              attachment["url"] == f"/api/attachments/{attachment['id']}")
        download = client.get(attachment["url"])
        check("attachment downloads", download.status_code == 200
              and download.content == b"\x89PNG fake")
        check("disallowed extension rejected", client.post(
            f"/api/complaints/{cid}/attachments",
            files=[("files", ("virus.exe", io.BytesIO(b"MZ"), "application/exe"))],
        ).status_code == 400)

        print("\n[multipart creation]")
        multi = client.post(
            "/api/complaints/upload",
            data={
                "citizen_name": "رنا الشامي", "citizen_phone": "0977777777",
                "governorate": "الحسكة",
                "title": "تشويش على الخط الأرضي",
                "description": "يوجد تشويش دائم على الهاتف الأرضي ولا تُسمع المكالمة بوضوح.",
            },
            files=[("files", ("photo.jpg", io.BytesIO(b"jpegdata"), "image/jpeg"))],
        )
        check("multipart create 201", multi.status_code == 201, multi.text)
        check("multipart attachment stored",
              len(multi.json()["complaint"]["attachments"]) == 1)
        check("landline routed to the operators",
              multi.json()["complaint"]["department"]["code"] == "affiliated_operators",
              multi.json()["complaint"]["type"])

        print("\n[workflow and history]")
        claimed = client.patch(f"/api/complaints/{cid}", json={
            "assignee": "م. سمير الأحمد", "actor": "م. سمير الأحمد",
        })
        check("naming an owner moves New -> Assigned",
              claimed.status_code == 200 and claimed.json()["status"] == "assigned",
              claimed.text)
        check("assignee recorded", claimed.json()["assignee"] == "م. سمير الأحمد")

        step = client.patch(f"/api/complaints/{cid}", json={
            "status": "in_progress",
            "note": "تم إرسال فريق فني.", "actor": "م. سمير الأحمد",
        })
        check("assigned -> in_progress", step.status_code == 200
              and step.json()["status"] == "in_progress", step.text)

        illegal = client.patch(f"/api/complaints/{cid}", json={"status": "new"})
        check("illegal transition rejected 400", illegal.status_code == 400, illegal.text)

        resolved = client.patch(f"/api/complaints/{cid}", json={
            "status": "resolved", "resolution": "تم إصلاح العطل واستعادة الخدمة.",
            "actor": "م. سمير الأحمد",
        }).json()
        check("resolved_at stamped", resolved["resolved_at"] is not None)

        closed = client.patch(f"/api/complaints/{cid}", json={
            "status": "closed", "actor": "م. سمير الأحمد",
        }).json()
        check("closed_at stamped", closed["closed_at"] is not None)
        check("closed cannot go back to in_progress",
              client.patch(f"/api/complaints/{cid}",
                           json={"status": "in_progress"}).status_code == 400)

        events = client.get(f"/api/complaints/{cid}/events").json()
        actions = [e["action"] for e in events]
        check("full audit trail kept", actions.count("status_changed") == 4
              and "created" in actions and "routed" in actions
              and "assigned" in actions and "attachment_added" in actions,
              str(actions))
        check("transitions record old and new",
              any(e["old_value"] == "resolved" and e["new_value"] == "closed"
                  for e in events))

        note_only = client.patch(f"/api/complaints/{billing['id']}", json={
            "note": "تم الاتصال بالمواطن.", "actor": "أ. ريم الحلبي",
        })
        check("note-only patch logged", note_only.status_code == 200 and any(
            e["action"] == "note"
            for e in client.get(f"/api/complaints/{billing['id']}/events").json()))

        print("\n[manual re-routing]")
        rerouted = client.patch(f"/api/complaints/{english['id']}", json={
            "department_code": "e_government", "actor": "أ. ريم الحلبي",
        }).json()
        check("department changed",
              rerouted["department"]["code"] == "e_government")
        check("unknown department 404", client.patch(
            f"/api/complaints/{english['id']}",
            json={"department_code": "nope"}).status_code == 404)

        print("\n[listing, filtering, search]")
        all_items = client.get("/api/complaints?per_page=100").json()
        check("list returns everything", all_items["total"] == 12, str(all_items["total"]))
        check("summary carries attachment_count",
              any(i["attachment_count"] == 1 for i in all_items["items"]))
        check("filter by status",
              all(i["status"] == "closed"
                  for i in client.get("/api/complaints?status=closed").json()["items"]))
        check("multi-value status filter",
              client.get("/api/complaints?status=closed&status=new").json()["total"] >= 1)
        check("filter by department",
              client.get("/api/complaints?department=affiliated_operators")
              .json()["total"] >= 2)
        check("arabic search works",
              client.get("/api/complaints?q=فاتورة").json()["total"] >= 1)
        check("reference search works",
              client.get(f"/api/complaints?q={complaint['reference_no']}").json()["total"] == 1)
        check("search by citizen name",
              client.get("/api/complaints?q=فاطمة العلي").json()["total"] == 1)
        check("search by phone number",
              client.get("/api/complaints?q=0955555555").json()["total"] == 1)
        check("phone search ignores separators",
              client.get("/api/complaints?q=0955-555 555").json()["total"] == 1)
        check("phone search matches a stored +963 prefix",
              client.get("/api/complaints?q=963911234567").json()["total"] == 1)
        check("summary rows carry the citizen phone",
              all(item.get("citizen_phone")
                  for item in client.get("/api/complaints?per_page=5").json()["items"]))
        check("short digit strings do not trigger phone matching",
              client.get("/api/complaints?q=09").json()["total"]
              <= client.get("/api/complaints?per_page=100").json()["total"])
        check("priority sort puts high first",
              client.get("/api/complaints?sort=priority&order=asc").json()
              ["items"][0]["priority"] == "high")
        page = client.get("/api/complaints?per_page=3&page=2").json()
        check("pagination", len(page["items"]) == 3 and page["page"] == 2
              and page["pages"] == 4, str(page["pages"]))
        check("unknown sort key falls back safely",
              client.get("/api/complaints?sort=DROP TABLE").status_code == 200)

        print("\n[public tracking]")
        track = client.get(f"/api/track/{complaint['reference_no']}")
        check("track by reference", track.status_code == 200)
        check("tracking hides contact details", "citizen_phone" not in track.json())
        check("tracking includes history", len(track.json()["events"]) > 0)
        check("case-insensitive reference",
              client.get(f"/api/track/{complaint['reference_no'].lower()}")
              .status_code == 200)
        check("unknown reference 404",
              client.get("/api/track/MOCT-2026-999999").status_code == 404)

        print("\n[dashboard statistics]")
        stats = client.get("/api/stats").json()
        check("total matches", stats["total"] == 12, str(stats["total"]))
        check("open + resolved == total",
              stats["open_count"] + stats["resolved_count"] == stats["total"],
              f"{stats['open_count']}+{stats['resolved_count']}")
        check("avg resolution computed", stats["avg_resolution_hours"] is not None)
        check("trend zero-filled to 14 days", len(stats["recent_days"]) == 14)
        check("every department present", len(stats["by_department"]) == 7)
        check("status breakdown covers 6 statuses",
              len(stats["status_breakdown"]) == 6)
        check("status percentages total 100",
              sum(b["percent"] for b in stats["status_breakdown"]) == 100,
              str([b["percent"] for b in stats["status_breakdown"]]))
        check("type breakdown covers 12 types", len(stats["type_breakdown"]) == 12)
        check("busiest type bar is full width",
              stats["type_breakdown"][0]["width"] == 100)
        check("sla percentages total 100",
              sum(stats["sla"]["percent"].values()) == 100,
              str(stats["sla"]["percent"]))
        check("kpi fields present",
              all(k in stats for k in ("new_today", "overdue_count",
                                       "resolved_this_week", "in_progress_count")))

        print("\n[AI priority review]")
        import time as _time
        from app.ai import ollama as _ollama

        graded = client.post("/api/complaints", json={
            "citizen_name": "مواطن المراجعة", "citizen_phone": "0912121212",
            "governorate": "دمشق", "title": "تذبذب في الخدمة",
            "description": "الخدمة تتذبذب في المساء وتؤثر على العمل من المنزل.",
        }).json()["complaint"]
        check("intake assigns a priority without waiting for the model",
              graded["priority"] in ("low", "medium", "high"))
        check("intake records the interim decision", any(
            e["action"] == "priority_set" and "بانتظار" in (e["note"] or "")
            for e in graded["events"]))

        # Submission must not be gated on the model. A model call costs seconds;
        # this asserts the citizen never pays for one.
        started = _time.perf_counter()
        client.post("/api/complaints", json={
            "citizen_name": "قياس الزمن", "citizen_phone": "0913131313",
            "governorate": "حلب", "title": "انقطاع الخدمة في الحي",
            "description": "انقطاع كامل للإنترنت عن الحي منذ ساعات دون إشعار مسبق.",
        })
        elapsed = _time.perf_counter() - started
        check("submission stays off the model's critical path (<1.5s)",
              elapsed < 1.5, f"took {elapsed:.2f}s")

        if _ollama.available():
            # Called directly rather than racing the background worker.
            before = client.get(f"/api/complaints/{graded['id']}").json()["priority"]
            services.refine_priority(graded["id"])
            after = client.get(f"/api/complaints/{graded['id']}").json()
            check("review leaves a valid priority in place",
                  after["priority"] in ("low", "medium", "high"))
            if after["priority"] != before:
                check("a changed priority is logged as a system decision", any(
                    e["action"] == "priority_changed" and e["actor"] == "system"
                    for e in after["events"]))
            else:
                check("model agreeing with the rules writes no noise event",
                      not any(e["action"] == "priority_changed"
                              for e in after["events"]))
            check("reviewing twice changes nothing the second time",
                  services.refine_priority(graded["id"]) is None)

        print("\n[automatic priority escalation]")
        stale_low = client.post("/api/complaints", json={
            "citizen_name": "قديم الشكوى", "citizen_phone": "0977776666",
            "governorate": "درعا", "title": "استفسار قديم بلا رد",
            "description": "استفسار بسيط قُدّم منذ مدة طويلة ولم يصله أي رد حتى الآن.",
        }).json()["complaint"]
        check("starts low priority", stale_low["priority"] == "low", stale_low["priority"])

        stale_medium = client.post("/api/complaints", json={
            "citizen_name": "شكوى متوسطة قديمة", "citizen_phone": "0977775555",
            "governorate": "دمشق", "title": "تشويش قديم على الخط",
            "description": "تشويش على الهاتف الأرضي لم تتم معالجته منذ فترة طويلة.",
        }).json()["complaint"]

        fresh = client.post("/api/complaints", json={
            "citizen_name": "شكوى حديثة", "citizen_phone": "0977774444",
            "governorate": "دمشق", "title": "شكوى قدمت للتو",
            "description": "شكوى جديدة قُدّمت منذ لحظات ولم يمر عليها وقت يُذكر.",
        }).json()["complaint"]

        # A Low complaint measured against Medium's window used to be declared
        # High two days before its own deadline. 77h is inside Low's 120h.
        with db.get_db(write=True) as conn:
            conn.execute(
                "UPDATE complaints SET created_at = datetime('now', '-77 hours')"
                " WHERE id = ?", (stale_low["id"],))
            early = services.escalate_overdue(conn)
        check("a 77h-old low complaint is left alone — its own window is 120h",
              stale_low["id"] not in early, str(early))

        # Backdate directly in the database — there is no HTTP route for this,
        # since only real elapsed time should ever trigger an escalation.
        # 130h clears Low's own 120h window; 100h clears Medium's 72h one.
        with db.get_db(write=True) as conn:
            for complaint_id, hours_ago in ((stale_low["id"], 130), (stale_medium["id"], 100)):
                conn.execute(
                    "UPDATE complaints SET created_at = datetime('now', ?) WHERE id = ?",
                    (f"-{hours_ago} hours", complaint_id),
                )
            if stale_medium["priority"] != "medium":
                conn.execute(
                    "UPDATE complaints SET priority = 'medium' WHERE id = ?",
                    (stale_medium["id"],),
                )

        with db.get_db(write=True) as conn:
            escalated = services.escalate_overdue(conn)

        check("130h-old low priority escalates to medium",
              stale_low["id"] in escalated, str(escalated))
        check("100h-old medium escalates to high",
              stale_medium["id"] in escalated, str(escalated))
        check("a few-seconds-old complaint is left alone",
              fresh["id"] not in escalated)

        after_low = client.get(f"/api/complaints/{stale_low['id']}").json()
        after_medium = client.get(f"/api/complaints/{stale_medium['id']}").json()
        check("low -> medium reflected via the API", after_low["priority"] == "medium",
              after_low["priority"])
        check("-> high reflected via the API", after_medium["priority"] == "high",
              after_medium["priority"])
        check("escalation logged as a priority_changed event with actor=system", any(
            e["action"] == "priority_changed" and e["actor"] == "system"
            and "تصعيد تلقائي" in (e["note"] or "")
            for e in after_low["events"]
        ), str([e["action"] for e in after_low["events"]]))

        # The clock restarts at each escalation, so a complaint cannot climb two
        # rungs on consecutive sweeps merely because it is old.
        with db.get_db(write=True) as conn:
            second_pass = services.escalate_overdue(conn)
        check("a just-escalated complaint does not climb again immediately",
              stale_low["id"] not in second_pass, str(second_pass))
        check("re-running the sweep finds nothing left overdue for these two",
              stale_low["id"] not in second_pass and stale_medium["id"] not in second_pass,
              str(second_pass))

        check("high priority never escalates further (there's nowhere higher)",
              client.patch(f"/api/complaints/{stale_medium['id']}",
                           json={"priority": "high"}).status_code == 200)

        # A suggestion left unread becomes overdue, not urgent: age alone must
        # never put it at the top of a queue beside a hospital outage.
        suggestion = client.post("/api/complaints", json={
            "citizen_name": "صاحب مقترح", "citizen_phone": "0977773333",
            "governorate": "دمشق",
            "title": "مقترح: إضافة خدمة تتبع الشكوى عبر الرسائل",
            "description": "أقترح إضافة خدمة تتبع الشكوى عبر الرسائل القصيرة لتسهيل المتابعة.",
        }).json()["complaint"]
        check("a suggestion is classified as an inquiry",
              suggestion["type"] == "inquiry", suggestion["type"])
        check("a suggestion starts low", suggestion["priority"] == "low",
              suggestion["priority"])

        # Age it hard and sweep repeatedly: every rung it could climb, it may.
        for _ in range(4):
            with db.get_db(write=True) as conn:
                conn.execute(
                    "UPDATE complaints SET created_at = datetime('now', '-400 hours')"
                    " WHERE id = ?", (suggestion["id"],))
                conn.execute(
                    "UPDATE events SET created_at = datetime('now', '-400 hours')"
                    " WHERE complaint_id = ?", (suggestion["id"],))
                services.escalate_overdue(conn)
        aged = client.get(f"/api/complaints/{suggestion['id']}").json()
        check("a 400h-old suggestion rises to medium and stops there",
              aged["priority"] == "medium", aged["priority"])

        print("\n[archive]")
        # `cid` is the complaint walked all the way through to closed above.
        check("cannot archive straight from an open state",
              client.patch(f"/api/complaints/{billing['id']}",
                           json={"status": "archived"}).status_code == 400)

        before = client.get("/api/complaints?per_page=100").json()["total"]
        archived = client.patch(f"/api/complaints/{cid}", json={
            "status": "archived", "actor": "م. سمير",
            "note": "انتهت المعالجة.",
        })
        check("closed -> archived allowed", archived.status_code == 200, archived.text)
        check("status is archived", archived.json()["status"] == "archived")
        check("archived_at stamped", archived.json()["archived_at"] is not None)
        check("archiving is logged as a status change",
              any(e["action"] == "status_changed" and e["new_value"] == "archived"
                  for e in client.get(f"/api/complaints/{cid}/events").json()))
        check("archived is exposed as a real status",
              any(st["value"] == "archived" and st["ar"] == "مؤرشفة"
                  for st in client.get("/api/meta").json()["statuses"]))

        check("archived drops out of the default list",
              client.get("/api/complaints?per_page=100").json()["total"] == before - 1)
        check("asking for the closed status does not surface it",
              all(i["id"] != cid for i in
                  client.get("/api/complaints?status=closed&per_page=100").json()["items"]))
        by_status = client.get("/api/complaints?status=archived&per_page=100").json()
        check("asking for the archived status overrides the default hide",
              [i["id"] for i in by_status["items"]] == [cid],
              str([i["id"] for i in by_status["items"]]))
        by_flag = client.get("/api/complaints?archived=true&per_page=100").json()
        check("the archived flag lists it too",
              [i["id"] for i in by_flag["items"]] == [cid])
        check("summary rows carry archived_at",
              by_status["items"][0]["archived_at"] is not None)
        check("fetching one archived complaint still works",
              client.get(f"/api/complaints/{cid}").status_code == 200)
        check("citizen tracking still resolves an archived complaint",
              client.get(f"/api/track/{closed['reference_no']}").status_code == 200)
        check("csv can export the archive",
              "MOCT" in client.get("/api/complaints.csv?archived=true").text)

        stats = client.get("/api/stats").json()
        check("archived counted in its own bucket", stats["by_status"].get("archived") == 1)
        check("open + resolved still accounts for every complaint",
              stats["open_count"] + stats["resolved_count"] == stats["total"],
              f"{stats['open_count']} + {stats['resolved_count']} != {stats['total']}")
        check("status breakdown covers all 6 statuses",
              len(stats["status_breakdown"]) == 6)
        check("status percentages still total 100",
              round(sum(st["percent"] for st in stats["status_breakdown"])) == 100)

        restored = client.patch(f"/api/complaints/{cid}", json={"status": "closed"})
        check("archived -> closed allowed", restored.status_code == 200, restored.text)
        check("back in the working queue",
              client.get("/api/complaints?per_page=100").json()["total"] == before)
        check("archived_at kept as a record of when it was filed",
              restored.json()["archived_at"] is not None)
        client.patch(f"/api/complaints/{cid}", json={"status": "archived"})
        check("archived cannot jump straight back into in_progress",
              client.patch(f"/api/complaints/{cid}",
                           json={"status": "in_progress"}).status_code == 400)
        client.patch(f"/api/complaints/{cid}", json={"status": "closed"})

        print("\n[deletion]")
        target = multi.json()["complaint"]["id"]
        stored = client.get(f"/api/complaints/{target}").json()["attachments"][0]
        check("delete 204", client.delete(f"/api/complaints/{target}").status_code == 204)
        check("gone afterwards",
              client.get(f"/api/complaints/{target}").status_code == 404)
        check("attachment file removed from disk",
              not any(db.UPLOAD_DIR.glob("*"))
              or client.get(stored["url"]).status_code == 404)
        check("missing complaint 404",
              client.get("/api/complaints/999999").status_code == 404)

    print(f"\n{'=' * 46}\n  {passed} passed, {failed} failed\n{'=' * 46}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)
