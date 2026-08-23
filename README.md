# منصة شكاوى وزارة الاتصالات وتقانة المعلومات

### Ministry of Communications — Complaint Classification and Routing Platform

Citizens submit complaints and inquiries about telecom and internet services.
The platform classifies each one, sets its priority, routes it to the
responsible department, issues a reference number, and tracks it through to
closure — with a staff dashboard over the whole queue.

Built for **CHALLENGE 03**. See [challenge-03-english.md](challenge-03-english.md)
and [challenge-03-arabic.md](challenge-03-arabic.md).

---

## Running it

Requires Python 3.11+.

```bash
pip install -r backend/requirements.txt
```

```bash
python -m uvicorn app.main:app --reload --port 8000 --app-dir backend
```

Then open <http://127.0.0.1:8000> — FastAPI serves both the API and the
frontend, so there is no second server and no build step.

Load sample complaints so the dashboard has something to draw:

```bash
cd backend && python seed.py --reset
```

Interactive API documentation is at <http://127.0.0.1:8000/docs>.

## Tests

```bash
cd backend && python test_api.py
```

```bash
cd backend && python test_live.py
```

77 in-process checks over the whole API, plus 10 checks that run against a real
uvicorn server to cover concurrency.

---

## The three screens

**الرئيسية** — hero with a reference-number tracking box, live platform
statistics, the six complaint categories (each showing its responsible
department), and the four-step explanation of how a complaint is handled.
Clicking a category opens the form with that type preselected.

**تقديم شكوى** — the submission form: type, governorate, title, description with
a 600-character counter, priority, drag-and-drop attachments, and contact
details. Validates inline in Arabic, then shows a receipt with the reference
number, the classification, the assigned department, and a warning if a similar
complaint already exists.

**لوحة الإدارة** — the staff dashboard: five KPI cards, complaints by category,
status distribution, a 14-day intake trend, SLA compliance, and a searchable,
filterable, paginated table wired to a detail panel that advances status,
re-routes to another department, and shows the full update log.

## Architecture

```
frontend/                 static, no build step
  index.html              the three screens
  css/app.css             design tokens and all styling
  js/api.js               API client
  js/format.js            Arabic numerals, dates, DOM helpers
  js/home.js              stats strip, category cards, tracking
  js/submit.js            form, validation, attachments, receipt
  js/admin.js             KPIs, charts, table, detail panel
  js/app.js               routing and shared label lookups

backend/                  FastAPI + SQLite
  app/domain.py           the vocabulary everything else agrees on
  app/db.py               connections, schema, seeding
  app/classifier.py       rule-based triage
  app/repository.py       all SQL
  app/services.py         business rules
  app/schemas.py          request/response models
  app/main.py             routes
```

The frontend is plain HTML, CSS and JavaScript — no framework and no bundler.
The design was delivered as an HTML prototype with inline styles; those became
CSS classes without changing a single measurement, and the markup is served
directly.

Arabic labels for every status, priority, type and department live in
`backend/app/domain.py` and reach the UI through `/api/meta`, so the two halves
cannot drift apart.

See [backend/README.md](backend/README.md) for the API reference, the triage
rules, the SLA model and the concurrency notes.

## Requirements coverage

| Requirement | Where |
| --- | --- |
| إنشاء شكوى | Submit form → `POST /api/complaints` |
| وصف المشكلة | `description`, 600-character limit enforced both sides |
| نوع الشكوى | Six types, auto-classified or chosen by the citizen |
| المرفقات | Up to 5 files, drag-and-drop, stored under random names |
| الأولوية | Three levels, suggested from urgency wording |
| حالة الشكوى | Five statuses with server-enforced transitions |
| سجل التحديثات | Append-only `events` table, rendered as the timeline |
| رقم مرجعي | Sequential `MOCT-2026-014287`, used by public tracking |
| التوجيه للجهة المسؤولة | Routing table from type to department, plus manual re-route |
| إحصائيات | `/api/stats` — KPIs, breakdowns, SLA compliance, intake trend |
| Dashboard | لوحة الإدارة |

## Design decisions worth knowing

- **The category cards are the canonical type list.** The prototype contained
  two different lists — six cards and six dropdown options that did not match,
  so clicking a card set the dropdown to a value it did not contain. The cards
  won (they carry codes, descriptions and departments) and the dropdown now
  shows the same six names, which fixes that flow.
- **Reference numbers use Latin digits** (`MOCT-2026-014287`) so they can be
  copied and retyped into the tracking box. Statistics and dates use
  Arabic-Indic digits exactly as designed.
- **A complaint starts as `جديدة` with its department already assigned.**
  Routing is automatic; ownership is not. It becomes `محوّلة` when a named
  officer takes it.
- **The submit form always sends a type**, so the receipt's "التصنيف الآلي"
  label reflects the design's wording rather than a live automatic
  classification. The classifier still runs on every submission and records a
  `classification_suggested` event when it disagrees, visible to staff in the
  update log. The API auto-classifies fully when `type` is omitted.
- **A responsive breakpoint was added below 900px.** The prototype is
  desktop-only and overflows on narrow screens. Nothing changes at desktop
  width.

## Not included

There is **no authentication** — the staff dashboard is open to anyone who can
reach it, and the `actor` recorded on each update is self-reported. This is the
first thing to add before any real deployment. CORS is also wide open for local
development.
