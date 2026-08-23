# Backend — FastAPI + SQLite

API for receiving, classifying, routing and tracking citizen complaints.

## Running

```bash
pip install -r requirements.txt
```

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Serves the API **and** the frontend at <http://127.0.0.1:8000>.
Interactive API docs: <http://127.0.0.1:8000/docs>

Sample data for the dashboard:

```bash
python seed.py --reset
```

Tests:

```bash
python test_api.py
```

```bash
python test_live.py
```

`test_api.py` runs 99 checks in-process against a throwaway database.
`test_live.py` starts a real uvicorn server and fires overlapping requests at
it — in-process tests serialise everything and cannot catch threadpool or
SQLite locking problems.

The database and uploads are created under `backend/data/` (override with the
`MOCT_DATA_DIR` environment variable).

## Layout

| File | Responsibility |
| --- | --- |
| `app/domain.py` | Statuses, priorities, types, departments, routing, SLA targets, AR/EN labels, chart colours |
| `app/db.py` | Connection handling, schema, seeding |
| `app/classifier.py` | Rule-based triage: type, priority, duplicate similarity |
| `app/repository.py` | All SQL, including the dashboard statistics |
| `app/services.py` | Business rules, attachments, CSV, serialization |
| `app/schemas.py` | Request/response models |
| `app/main.py` | Routes, and the static mount that serves the frontend |

## Data model

- **complaints** — `reference_no`, citizen details, type, priority, status,
  owning department, assignee, resolution, timestamps.
- **departments** — the seven responsible entities and the domain each owns,
  reconciled against `domain.DEPARTMENTS` on every start: renames update in
  place so complaints keep their routing, and a retired department is only
  removed once nothing references it.
- **attachments** — files on disk plus their metadata.
- **events** — the append-only update log; every change writes a row here.

## Vocabulary

Seven entities receive complaints, each owning a stated problem domain:

| Code | Entity | Domain |
| --- | --- | --- |
| `digital_transformation` | مديرية التحول الرقمي | رقمنة الخدمات الحكومية، أتمتة المعاملات، وربط الجهات الحكومية |
| `information_technology` | مديرية تقانة المعلومات | الأنظمة الحكومية، قواعد البيانات، والتكامل بين الأنظمة |
| `telecommunications` | مديرية الاتصالات | مشاكل الاتصالات، جودة الخدمة، البنية التحتية، وتغطية الشبكات |
| `e_government` | مديرية المعلوماتية والحكومة الإلكترونية | تطوير البوابات والمنصات الحكومية والخدمات الإلكترونية |
| `cybersecurity` | الجهات المعنية بالأمن السيبراني | حماية البيانات والأنظمة الحكومية، واكتشاف التهديدات |
| `data_statistics` | الجهات المعنية بالبيانات والإحصاء الرقمي | جمع البيانات، تحليلها، ولوحات المعلومات لدعم القرار |
| `affiliated_operators` | الجهات التابعة للوزارة ومؤسسات الاتصالات | الخدمات المقدَّمة مباشرة للمواطنين |

Twelve complaint types route into them. Every entity receives at least one
type — a department nothing routes to would never see work:

| Code | Type | Routed to |
| --- | --- | --- |
| C-01 | انقطاع خدمة الإنترنت | مديرية الاتصالات |
| C-02 | بطء السرعة وجودة الخدمة | مديرية الاتصالات |
| C-03 | البنية التحتية وتغطية الشبكات | مديرية الاتصالات |
| C-04 | الهاتف الأرضي | الجهات التابعة ومؤسسات الاتصالات |
| C-05 | الفواتير والرصيد | الجهات التابعة ومؤسسات الاتصالات |
| C-06 | استفسار أو مقترح | الجهات التابعة ومؤسسات الاتصالات |
| C-07 | البوابات والمنصات الحكومية | المعلوماتية والحكومة الإلكترونية |
| C-08 | الخدمات الإلكترونية للمواطن | المعلوماتية والحكومة الإلكترونية |
| C-09 | رقمنة وأتمتة المعاملات | مديرية التحول الرقمي |
| C-10 | الأنظمة وقواعد البيانات | مديرية تقانة المعلومات |
| C-11 | الأمن السيبراني وحماية البيانات | الجهات المعنية بالأمن السيبراني |
| C-12 | البيانات والإحصاء الرقمي | الجهات المعنية بالبيانات والإحصاء الرقمي |

Priorities: `منخفضة` `متوسطة` `عالية`.
Statuses: `جديدة` `محوّلة` `قيد المعالجة` `تم الحل` `مغلقة`.

Every label lives in `domain.py` and reaches the UI through `/api/meta`, so the
API and the screens cannot drift apart.

## How a complaint is triaged

`app/classifier.py` scores the title and description against Arabic and English
keyword sets, then:

1. **Classifies** it into one of the twelve types. Arabic is normalized first —
   diacritics stripped, `أإآ→ا`, `ى→ي`, `ة→ه` — so spelling variants match.
2. **Assigns a priority** from urgency wording (`انقطاع كامل`, `طارئ`, `متكرر`,
   `emergency` → عالية; inquiries and suggestions → منخفضة). A suspected
   breach starts at عالية by type, the same way a total outage does.
3. **Routes** it to the owning department from the table above.
4. **Flags possible duplicates** — same-type complaints from the last 30 days
   with ≥72% text similarity, returned to the citizen at submission time.

A complaint is created as `جديدة` with its department already set: routing is
automatic, but it stays on the new pile until someone takes ownership. Naming an
assignee moves it to `محوّلة`.

Anything the citizen selects explicitly overrides the inferred value. When the
classifier disagrees with the citizen's choice it records a
`classification_suggested` event so the reviewing officer sees the alternative
in the update log.

## Workflow

```
جديدة ──> محوّلة ──> قيد المعالجة ──> تم الحل ──> مغلقة
```

Transitions are enforced server-side (`ALLOWED_TRANSITIONS`); an illegal move
returns 400 and `مغلقة` is terminal. Reaching `تم الحل` stamps `resolved_at`,
`مغلقة` stamps `closed_at`, and both feed the average-resolution metric.

## SLA and automatic escalation

`SLA_HOURS` in `domain.py` sets the resolution window per priority — عالية 24h,
متوسطة 72h, منخفضة 120h. A complaint past 75% of its window counts as
*قاربت المهلة* and past 100% as *متأخرة*. Resolved complaints are measured
against how long they actually took, open ones against how long they have been
waiting. This drives the compliance bar and the overdue KPI.

A complaint left open too long **raises its own priority**. A background sweep
runs every 60 seconds (`ESCALATION_INTERVAL_SECONDS` in `main.py`, plus one
pass at startup) and applies `escalate_priority()` from `domain.py`:

| Waiting longer than | Effect |
| --- | --- |
| the متوسطة window (72h) | anything below عالية becomes عالية |
| the عالية window (24h) | منخفضة becomes متوسطة |

The rule reuses the SLA numbers rather than inventing a second set of
thresholds. Escalation only ever raises a priority, never lowers one a human
set deliberately, and skips complaints that are already عالية, تم الحل or
مغلقة. Each bump writes a normal `priority_changed` event with `actor="system"`
and a note saying how long the complaint had waited, so it appears in the
update log exactly like a human-made change. The sweep is idempotent — running
it twice in a row changes nothing the second time.

## Endpoints

### Meta
| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness check |
| GET | `/api/meta` | Statuses, priorities, types (with card codes, blurbs, departments), governorates, workflow order and legal transitions — all with `ar`/`en` labels |

### Complaints
| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/complaints` | Create from JSON |
| POST | `/api/complaints/upload` | Create from `multipart/form-data` with attachments |
| GET | `/api/complaints` | List — filter, search, sort, paginate |
| GET | `/api/complaints.csv` | Same filters, as a CSV download (UTF-8 BOM for Excel) |
| GET | `/api/complaints/{id}` | Full detail with attachments and history |
| PATCH | `/api/complaints/{id}` | Change status, priority, type, department, assignee, resolution |
| DELETE | `/api/complaints/{id}` | Delete the complaint and its files |
| GET | `/api/complaints/{id}/events` | The update log |

List parameters: `status`, `type`, `priority` (repeatable for multi-select),
`department`, `assignee`, `q`, `sort` (`created_at`, `updated_at`, `priority`,
`status`, `reference_no`), `order`, `page`, `per_page` (max 100).

`q` searches the title, description, reference number, citizen name, phone and
detailed address. Phone matching strips separators from both sides, so
`0955 512-345` finds a number stored as `0955512345`.

### Attachments
| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/complaints/{id}/attachments` | Upload files |
| GET | `/api/attachments/{id}` | Download one |

Up to 5 files per complaint, 10 MB each server-side (the form advertises 5 MB),
restricted to images, PDF, Office documents, text, MP4 and MP3. Stored under a
random UUID name so a hostile filename can never escape the upload directory.

### Tracking (public)
| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/track/{reference_no}` | Status and history by reference number |

Omits the citizen's name, phone and email, so a reference number alone never
leaks contact details. Lookup is case-insensitive.

### Dashboard
| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/stats?days=14` | KPIs, status/type breakdowns with chart colours and percentages, SLA compliance, and a zero-filled daily trend |

## Concurrency notes

Two things are load-bearing and easy to break:

- `check_same_thread=False` — FastAPI runs a sync dependency's setup and its
  teardown on **different** threadpool threads. Without this, `conn.close()`
  raises `ProgrammingError` under real concurrent traffic. Each request still
  owns its connection exclusively.
- **`BEGIN IMMEDIATE` for writers** (`get_db(write=True)`) — a transaction that
  starts as a reader and later tries to write gets `SQLITE_BUSY` the instant
  another writer is active, and `busy_timeout` does not cover that upgrade.
  Taking the write lock up front is what lets concurrent submissions succeed.
  Read-only routes use `db_dependency`; mutating routes use
  `write_db_dependency`.

`test_live.py` covers both.

## Known limitations

- **No authentication.** Every staff endpoint is open, and the `actor` field on
  updates is self-reported. Putting the dashboard behind auth is the first thing
  to add before any real deployment.
- **CORS is open** (`allow_origins=["*"]`) for local development. Restrict it to
  the real origin before deploying.
- Attachments are stored on the local filesystem, not object storage.
