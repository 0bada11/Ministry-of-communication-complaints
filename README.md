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

Requires Python 3.11+, and [Ollama](https://ollama.com) for the AI features.

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

### AI features

The assistant and AI priority run on a local Ollama. Pull the two models once:

```bash
ollama pull gemma3:4b && ollama pull nomic-embed-text
```

Then build the chatbot's index from the knowledge base:

```bash
cd backend && python ingest.py --reset
```

Re-run that whenever `docs/knowledge-base.md` changes. Everything works with
Ollama stopped — complaints are still accepted, classified and routed, the
priority falls back to the rule-based classifier, and the chat launcher simply
does not appear.

## Tests

```bash
cd backend && python test_api.py
```

```bash
cd backend && python test_live.py
```

```bash
cd backend && python test_retrieval.py
```

107 in-process checks over the whole API, 10 against a real uvicorn server for
concurrency, and a 34-question retrieval evaluation in both languages.

---

## The three screens

**الرئيسية** — hero with a reference-number tracking box, live platform
statistics, the twelve complaint categories (each showing the entity
responsible for it), and the four-step explanation of how a complaint is handled.
Clicking a category opens the form with that type preselected.

**تقديم شكوى** — the submission form: type, governorate, a detailed address
(street, building number, floor, nearest landmark), title, description with a
600-character counter, priority, drag-and-drop attachments, and contact details.
Validates inline in Arabic, then shows a receipt with the reference number, the
classification, the assigned department, and a warning if a similar complaint
already exists.

**لوحة الإدارة** — split into two tabs, matching how the work actually divides:

- **لوحة المؤشرات** — reporting only. Five KPI cards, complaints by category,
  status distribution, a 14-day intake trend and SLA compliance. No
  per-complaint actions live here.
- **الشكاوى الواردة** — the working queue. A full-width table showing each
  complaint's reference, subject, citizen name and phone, department, priority
  and status. Search covers reference, subject, citizen name, phone and address;
  filters cover status, category, department, priority and sort order, with a
  badge counting how many are active and one click to clear them. Selecting a
  row opens the complaint in **focus mode** — a full overlay with its contact
  details, address, attachments and complete update log, plus the buttons that
  advance its status or re-route it. Closes on Esc, backdrop click or the close
  button.

## Architecture

```
frontend/                 static, no build step
  index.html              the three screens
  css/app.css             design tokens and all styling
  js/motion.js            spring solver, velocity tracking, projection
  js/api.js               API client
  js/format.js            Arabic numerals, dates, DOM helpers
  js/home.js              stats strip, category cards, tracking
  js/submit.js            form, validation, attachments, receipt
  js/admin.js             KPIs, charts, queue table, filters, focus mode
  js/chat.js              the citizen assistant panel
  js/app.js               routing and shared label lookups

backend/                  FastAPI + SQLite
  app/domain.py           the vocabulary everything else agrees on
  app/db.py               connections, schema, seeding
  app/classifier.py       rule-based triage
  app/repository.py       all SQL
  app/services.py         business rules
  app/schemas.py          request/response models
  app/main.py             routes
  app/tasks.py            single worker for model calls
  app/ai/                 Ollama client, chunker, hybrid store, RAG, priority
  ingest.py               builds the vector index

docs/
  knowledge-base.md       what the chatbot is allowed to answer from
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
| نوع الشكوى | Twelve types, auto-classified or chosen by the citizen |
| المرفقات | Up to 5 files, drag-and-drop, stored under random names |
| الأولوية | Three levels, assigned by the AI from the description (never by the citizen), escalated automatically when a complaint waits too long |
| حالة الشكوى | Five statuses with server-enforced transitions |
| سجل التحديثات | Append-only `events` table, rendered as the timeline |
| رقم مرجعي | Sequential `MOCT-2026-014287`, used by public tracking |
| التوجيه للجهة المسؤولة | Routing table from type to one of seven entities, plus manual re-route |
| إحصائيات | `/api/stats` — KPIs, breakdowns, SLA compliance, intake trend |
| Dashboard | لوحة المؤشرات (charts) + الشكاوى الواردة (queue) |

## Motion

Everything a person can touch animates through a spring rather than a fixed
duration, because a spring retargets from its *current* value and velocity —
which is what lets a moving element be grabbed and reversed mid-flight without
a jump. `js/motion.js` is a ~200-line solver written for this project (no
bundler, so no dependency) using Apple's two parameters instead of the physics
triplet: **damping** (overshoot) and **response** (how fast it converges, in
seconds — not a duration).

Three presets carry the house style. Bounce is reserved for motion the user's
own gesture set going: a sheet released from a drag is allowed to overshoot, a
panel that merely appeared is not.

| Preset | Damping | Response | Used for |
| --- | --- | --- | --- |
| `ui` | 1.0 | 0.35 | default — settles without bouncing |
| `move` | 1.0 | 0.4 | counters and repositioning |
| `sheet` | 0.8 | 0.3 | released from a drag |

What actually moves:

- **Press feedback** on every control, fired on pointer-*down* rather than
  release. Pressing in is faster than springing back; large surfaces get a
  smaller scale than small ones so the travel reads equal at every size, and
  table rows respond with colour instead of geometry.
- **The focus sheet can be dragged down to dismiss.** It tracks the finger 1:1,
  resists with progressive rubber-banding if pulled upward past home, and the
  scrim thins as it is pulled away. On release the landing point is *projected*
  from the throw velocity, so a short flick dismisses while the same distance
  held still springs back. Release velocity is handed to the spring, so there
  is no seam between dragging and animating.
- **Charts animate from their previous value, not from zero.** One long-lived
  spring per series means the first paint is an entrance and every later
  refresh eases from whatever is on screen — no replaying the entrance each
  time data arrives, and a refresh landing mid-flight has nothing to jump from.
  Bars scale rather than resize, so it stays a compositor-only transform.
- **Figures count** to their new value instead of snapping.

Accessibility is handled at the source: `prefers-reduced-motion` makes every
spring land immediately (state still changes, travel does not), and
`prefers-reduced-transparency` and `prefers-contrast` frost or solidify the
sheet. Because the springs short-circuit rather than being skipped, the UI is
fully correct with all motion removed. Springs also settle immediately when the
tab is backgrounded, since `requestAnimationFrame` stops there and anything
sequenced off a completion callback would otherwise hang.

## Design decisions worth knowing

- **The category cards are the canonical type list.** The prototype contained
  two different lists — cards and dropdown options that did not match, so
  clicking a card set the dropdown to a value it did not contain. The cards won
  (they carry codes, descriptions and owning entities) and the dropdown shows
  exactly the same names, which fixes that flow.
- **Twelve types, not six, because there are seven entities.** Four of the
  ministry's entities — digital transformation, information technology,
  cybersecurity, and data and statistics — own domains no telecom-only category
  touches. Swapping the departments alone would have left those four with a
  permanently empty queue, so the categories were extended to cover each stated
  domain. The home grid stays three columns and becomes 3×4.
- **The dashboard's category chart shows the top six.** It sits beside the donut
  in a stretched row; all twelve bars would run to twice the height of its
  neighbours. The full breakdown stays in `/api/stats` and in the CSV export.
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
- **Priority escalates on age, never downward.** A complaint waiting longer
  than the متوسطة SLA window becomes عالية; one waiting longer than the عالية
  window is lifted from منخفضة to متوسطة. The thresholds reuse the existing SLA
  numbers instead of introducing a second set, and the sweep never lowers a
  priority a person set deliberately. See [backend/README.md](backend/README.md).
- **Managing a complaint moved out of the dashboard.** The prototype put a
  cramped detail panel beside the table; complaint handling now lives in the
  الشكاوى الواردة tab, and opening one uses a focus overlay so the full history
  and contact details fit without scrolling a 430px column.

## Not included

There is **no authentication** — the staff dashboard is open to anyone who can
reach it, and the `actor` recorded on each update is self-reported. This is the
first thing to add before any real deployment. CORS is also wide open for local
development.
