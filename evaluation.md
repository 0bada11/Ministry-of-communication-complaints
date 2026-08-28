# Project Evaluation — Ministry of Communications Complaints Platform

> **تقييم منصة شكاوى وزارة الاتصالات وتقانة المعلومات**
>
> Every number in this document was produced by executing the system on
> 2026-08-28. Nothing here is estimated. Where a result is unfavourable it is
> reported as measured, and the limitations of each method are stated with it.

---

## Table of contents

| # | Section |
|---|---|
| 1 | [Evaluation methodology](#1-evaluation-methodology) |
| 2 | [System scale](#2-system-scale) |
| 3 | [Triage engine — type classification](#3-triage-engine--type-classification) |
| 4 | [Triage engine — priority assignment](#4-triage-engine--priority-assignment) |
| 5 | [Routing accuracy](#5-routing-accuracy) |
| 6 | [Duplicate detection](#6-duplicate-detection) |
| 7 | [Retrieval quality (RAG)](#7-retrieval-quality-rag) |
| 8 | [Answer quality (RAG)](#8-answer-quality-rag) |
| 9 | [Latency](#9-latency) |
| 10 | [Test suite coverage](#10-test-suite-coverage) |
| 11 | [Known defects and limitations](#11-known-defects-and-limitations) |
| 12 | [Summary scorecard](#12-summary-scorecard) |

---

## 1. Evaluation methodology

### 1.1 Metrics used and why

| Metric | Definition | Where used | Why this metric |
|---|---|---|---|
| **Accuracy** | correct ÷ total | type, priority, routing | Headline figure; honest only when classes are balanced, which is why it is never reported alone here. |
| **Precision** | TP ÷ (TP + FP) | per class, duplicates | "When it says X, how often is it right?" Governs false-alarm cost. |
| **Recall** | TP ÷ (TP + FN) | per class, duplicates | "Of the real X, how many did it find?" Governs miss cost. |
| **F1** | harmonic mean of P and R | per class | Single number when precision and recall trade off. Harmonic, so one bad half drags it down. |
| **Macro-F1** | unweighted mean of per-class F1 | type, priority | Treats a rare class as equal to a common one. The honest number when support is uneven. |
| **Weighted-F1** | F1 weighted by class support | type, priority | Reflects real-world mix instead of class equality. |
| **Confusion pairs** | gold → predicted counts | type, priority | Shows *which* mistakes happen, not just how many. |
| **hit@k** | share of queries whose correct section is in the top *k* | retrieval | Standard IR measure. hit@3 matters because the model receives several passages. |
| **Groundedness rate** | answers built from retrieved passages | RAG | A government assistant inventing policy is the primary risk. |
| **Refusal correctness** | out-of-scope questions correctly declined | RAG | Knowing when *not* to answer is a capability, not a failure. |
| **p50 / p95 latency** | median / 95th percentile | all endpoints | p95 rather than mean, because the mean hides the slow tail users actually notice. |

### 1.2 Labelling rubric

The triage test set was labelled **before** running the classifier, and priority
was labelled by **service impact**, deliberately *not* by the system's own
keyword list — otherwise the test would be circular and would score ~100% by
construction.

| Priority | Rubric applied by hand |
|---|---|
| **High** | Service fully down, a critical facility affected (hospital / emergency), a security incident, or a repeated failure already reported and unresolved. |
| **Medium** | Degraded service, billing errors, single-user faults. |
| **Low** | A pure question, a suggestion, or an administrative request with no service impact. |

### 1.3 Threats to validity

These are real and worth stating plainly:

1. **The labeller wrote the test set.** 60 complaints authored and labelled by
   the same evaluator. Phrasing may unconsciously favour vocabulary the system
   knows. An independent set written by ministry staff would be stronger.
2. **Sample sizes are small.** 60 triage cases, 14 duplicate pairs, 34
   retrieval questions, 18 assistant questions. Enough to expose systematic
   faults; not enough for tight confidence intervals. A single duplicate-pair
   error moves F1 by ~0.08.
3. **Single-machine latency.** One host, one user, a 24-row database. These
   are floor figures, not load-test results. No concurrency was measured.
4. **Retrieval ground truth is section-level**, not passage-level, and some
   questions accept two sections as correct.

---

## 2. System scale

### 2.1 Backend (Python)

| Module | Lines | Responsibility |
|---|---:|---|
| `app/repository.py` | 526 | All SQL |
| `app/services.py` | 524 | Business rules |
| `app/main.py` | 414 | HTTP routes |
| `app/domain.py` | 312 | Vocabulary, routing, SLA |
| `app/ai/store.py` | 274 | Hybrid retrieval index |
| `app/schemas.py` | 220 | Request/response models |
| `app/db.py` | 207 | Schema, connections, migrations |
| `app/classifier.py` | 185 | Rule-based triage |
| `app/ai/rag.py` | 162 | Retrieval-augmented answering |
| `app/ai/priority.py` | 145 | Model-based priority review |
| `app/ai/chunker.py` | 131 | Knowledge-base chunking |
| `app/ai/ollama.py` | 112 | Model client |
| `app/tasks.py` | 83 | Background worker |
| `app/ai/config.py` | 52 | AI configuration |
| **Application total** | **3 347** | |
| Tests (`test_api`, `test_live`, `test_retrieval`) | 915 | |
| Tooling (`seed.py`, `ingest.py`) | 257 | |
| **Backend total** | **4 519** | |

### 2.2 Frontend (no framework, no build step)

| File | Lines |
|---|---:|
| `css/app.css` | 1 550 |
| `js/admin.js` | 1 036 |
| `index.html` | 400 |
| `js/submit.js` | 233 |
| `js/chat.js` | 240 |
| `js/motion.js` | 220 |
| `js/app.js` | 146 |
| `js/format.js` | 114 |
| `js/api.js` | 95 |
| `js/home.js` | 88 |
| **Frontend total** | **4 122** |

**Whole project: 8 641 lines**, zero frontend dependencies, zero build step.

### 2.3 API surface — 16 endpoints

| Tag | Count | Endpoints |
|---|---:|---|
| complaints | 8 | create, create-multipart, list, CSV export, get, patch, delete, events |
| assistant | 2 | `/api/chat`, `/api/ai/health` |
| attachments | 2 | upload, download |
| meta | 2 | `/api/meta`, `/api/health` |
| dashboard | 1 | `/api/stats` |
| tracking | 1 | `/api/track/{ref}` |

### 2.4 Domain model

| Dimension | Count |
|---|---:|
| Complaint types | 12 |
| Departments | 7 |
| Workflow statuses | 6 |
| Priority levels | 3 |
| Governorates | 14 |
| Knowledge-base size | 37 580 chars / 1 021 lines |
| Indexed chunks | 69 |

---

## 3. Triage engine — type classification

**Test set:** 60 hand-labelled complaints, 5 per category across all 12 categories (balanced by design, so macro- and weighted-F1 coincide).

### 3.1 Headline

| Metric | Result |
|---|---:|
| Accuracy | **58 / 60 = 96.7 %** |
| Macro-F1 | **0.966** |
| Weighted-F1 | **0.966** |

### 3.2 Per class

| Category | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Internet Outage | 5 | 0.833 | 1.000 | 0.909 |
| Speed and Service Quality | 5 | 1.000 | 1.000 | **1.000** |
| Infrastructure and Network Coverage | 5 | 1.000 | 1.000 | **1.000** |
| Landline | 5 | 1.000 | 0.800 | 0.889 |
| Billing and Balance | 5 | 0.833 | 1.000 | 0.909 |
| Inquiry or Suggestion | 5 | 1.000 | 1.000 | **1.000** |
| Government Portals and Platforms | 5 | 1.000 | 1.000 | **1.000** |
| Citizen E-Services | 5 | 1.000 | 0.800 | 0.889 |
| Service Digitization and Automation | 5 | 1.000 | 1.000 | **1.000** |
| Systems and Databases | 5 | 1.000 | 1.000 | **1.000** |
| Cybersecurity and Data Protection | 5 | 1.000 | 1.000 | **1.000** |
| Data and Digital Statistics | 5 | 1.000 | 1.000 | **1.000** |

**8 of 12 categories are perfect.** No category scores below F1 0.889.

### 3.3 The two errors

| Gold | Predicted | Cause |
|---|---|---|
| Landline | Internet Outage | "الشبكة الثابتة مقطوعة عن المنزل" — *مقطوع* is an outage keyword and outranked the landline signal. |
| Citizen E-Services | Billing and Balance | "طلبت شهادة الكترونية **ودفعت الرسوم**" — the payment wording pulled it to billing. |

Both are **keyword-collision** errors, not misunderstandings: the text genuinely contains vocabulary from both categories. Both are recoverable — a reviewing officer reclassifies in one click, and the system logs a `classification_suggested` event whenever its own guess differs from the citizen's choice.

---

## 4. Triage engine — priority assignment

Same 60 complaints, labelled by the **service-impact rubric** in §1.2.

### 4.1 Headline

| Metric | Result |
|---|---:|
| Accuracy | **54 / 60 = 90.0 %** |
| Macro-F1 | **0.882** |
| Weighted-F1 | **0.901** |

### 4.2 Per class

| Priority | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Low | 7 | 0.857 | 0.857 | 0.857 |
| Medium | 39 | 0.946 | 0.897 | 0.921 |
| High | 14 | 0.812 | **0.929** | 0.867 |

### 4.3 Error direction — the important part

| Gold → Predicted | Count | Direction |
|---|---:|---|
| Medium → High | 3 | over-escalation (safe) |
| Medium → Low | 1 | under-escalation (unsafe) |
| High → Medium | 1 | under-escalation (unsafe) |
| Low → Medium | 1 | over-escalation (safe) |

**High recall is 0.929** — of 14 genuinely urgent complaints the system caught 13. Its precision is lower (0.812) because it over-escalates 3 medium cases.

That asymmetry is the correct direction for a public-service system: an over-escalated billing complaint wastes an officer's attention; an under-escalated hospital outage is a failure of the service. **The single High→Medium miss** is the one result in this evaluation that deserves follow-up work.

---

## 5. Routing accuracy

Department assignment is a **pure function of type** (`ROUTING` maps each of the 12 types to exactly one of 7 departments), so routing can only fail where type fails.

| Metric | Result |
|---|---:|
| Correct department | **58 / 60 = 96.7 %** |
| Departments reachable | 7 / 7 |
| Types with a defined owner | 12 / 12 |

No complaint can be created without a department, and no department exists that nothing routes to — both verified by the test suite.

---

## 6. Duplicate detection

**Test set:** 14 labelled pairs — 6 true duplicates (same problem, reworded) and 8 **hard negatives** (same category, genuinely different problem). Hard negatives were chosen deliberately; a test using unrelated pairs would score 100 % and prove nothing.

**Method:** normalised `SequenceMatcher` ratio over title + description, compared against the deployed threshold of **0.72**.

### 6.1 At the deployed threshold

| | Flagged | Not flagged |
|---|---:|---:|
| **Is a duplicate** | TP = 6 | FN = 0 |
| **Is not a duplicate** | FP = 1 | TN = 7 |

| Metric | Result |
|---|---:|
| Precision | 0.857 |
| Recall | **1.000** |
| F1 | 0.923 |
| Accuracy | 92.9 % |

**Recall is perfect** — no genuine duplicate was missed. Duplicate scores ranged 0.893 – 1.000; true negatives clustered at 0.252 – 0.471. The separation is wide.

### 6.2 The false positive

Two complaints about **different neighbourhoods** — حي المزة vs حي الميدان — scored **0.844**. The sentences are structurally identical and differ only in a place name and a day count, so a character-level measure sees them as near-identical. This is the known weakness of `SequenceMatcher`: it has no concept of which words carry meaning.

### 6.3 Threshold sweep

| Threshold | TP | FP | TN | FN | Precision | Recall | F1 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.50 – 0.84 | 6 | 1 | 7 | 0 | 0.857 | 1.000 | 0.923 |
| **0.72 (deployed)** | 6 | 1 | 7 | 0 | 0.857 | 1.000 | 0.923 |
| **0.86** | 6 | 0 | 8 | 0 | **1.000** | **1.000** | **1.000** |
| 0.88 | 6 | 0 | 8 | 0 | 1.000 | 1.000 | 1.000 |
| 0.90 – 0.94 | 5 | 0 | 8 | 1 | 1.000 | 0.833 | 0.909 |
| 0.96 | 3 | 0 | 8 | 3 | 1.000 | 0.500 | 0.667 |

**Finding:** performance is completely flat from 0.50 to 0.84 — the threshold is not doing any work in that range. **0.86 is optimal on this set** (F1 = 1.000), and 0.90 is where recall starts to fall.

**Recommendation (not yet applied):** raise `DUPLICATE_THRESHOLD` from 0.72 to **0.86**. Caveat: this is 14 pairs, and the gain rests on a single false positive. It should be confirmed on a larger set before being treated as settled.

---

## 7. Retrieval quality (RAG)

**Test set:** 34 questions (17 Arabic, 17 English) with the correct knowledge-base section labelled. **Corpus:** 69 chunks.

**Method:** each retriever scored independently over the identical question set. Hybrid fusion is Reciprocal Rank Fusion, `k = 60`, sparse weighted 1.0 and dense 0.5.

### 7.1 Results

| Retriever | hit@1 | hit@3 |
|---|---:|---:|
| Sparse only (BM25) | 21/34 = **61.8 %** | 34/34 = **100.0 %** |
| Dense only (vectors) | 19/34 = **55.9 %** | 29/34 = **85.3 %** |
| **Hybrid (RRF)** | **25/34 = 73.5 %** | **34/34 = 100.0 %** |

### 7.2 Does the hybrid earn its complexity?

Yes, and this is the measurement that justifies the design:

- Hybrid beats sparse alone by **+11.7 points** at hit@1 (73.5 % vs 61.8 %).
- Hybrid beats dense alone by **+17.6 points** at hit@1 and **+14.7** at hit@3.
- **hit@3 is 100 %** — for every question in the set, the correct section is among the passages handed to the model. Since the model receives the top *k* = 5, retrieval is never the limiting factor on this set.

The two retrievers fail on different questions, which is exactly the condition under which fusion helps: BM25 handles exact Arabic terminology, vectors handle paraphrase, and RRF lets each rescue the other.

---

## 8. Answer quality (RAG)

**Test set:** 18 questions — 15 in scope (10 Arabic, 5 English) and 3 deliberately out of scope. **Model:** `gemma3:4b` via Ollama, `nomic-embed-text` for embeddings.

### 8.1 In-scope questions (n = 15)

| Metric | Result |
|---|---:|
| Grounded in retrieved passages | **15 / 15 = 100 %** |
| Cited at least one source | **15 / 15 = 100 %** |
| Answered in the language asked | **15 / 15 = 100 %** |
| Complete (no trailing ellipsis) | **15 / 15 = 100 %** |
| Mean answer length | 161 chars |

Answers cited **2–4 sources** each, de-duplicated by section. Language matching held perfectly in both directions — Arabic questions never drifted into English despite retrieval frequently returning passages in the other language.

> **Regression note.** "Complete: 15/15" is a *fixed* defect, not a free pass. Before the fix, the assistant terminated answers with an ellipsis after ~34 tokens of a 500-token budget — `done_reason: "stop"`, so it was choosing to trail off, not being cut short. The cause was a system-prompt rule instructing brevity, which the model resolved by eliding lists. The rule was rewritten and an explicit anti-ellipsis rule added.

### 8.2 Out-of-scope questions (n = 3)

| Question | Behaviour | Correct? |
|---|---|:--:|
| ما هي عاصمة فرنسا؟ | Declines, explains the platform's scope, redirects to 1556 | ✅ |
| كم سعر صرف الدولار اليوم؟ | States the information is not held, redirects to 1556 | ✅ |
| What is the weather tomorrow? | Returns unrelated platform content (SLA escalation + tracking box) instead of declining | ❌ |

**Refusal correctness: 2 / 3.** The failure is reported rather than smoothed over — see §11.

### 8.3 A caveat on the `grounded` flag

All 18 questions returned `grounded: true`, **including the out-of-scope ones**. The flag means "retrieval returned passages above `MIN_SCORE` (0.012)", not "the answer is correct". Weak incidental term overlap clears that floor even for irrelevant questions. The flag is a UI signal for whether to show sources — it is **not** a correctness measure, and should not be read as one.

---

## 9. Latency

**Conditions:** single host, single user, warm process, 24-row database, `gemma3:4b` resident in memory. Warm-up calls excluded. n = 30 per read endpoint, n = 25 for intake, n = 18 for chat.

### 9.1 Read endpoints

| Endpoint | min | **p50** | **p95** | max |
|---|---:|---:|---:|---:|
| `GET /api/health` | 1.3 | **3.5** | **16.4** | 16.4 |
| `GET /api/meta` | 4.6 | **6.0** | **15.7** | 15.7 |
| `GET /api/track/{ref}` | 4.9 | **8.1** | **21.0** | 22.8 |
| `GET /api/complaints` (list) | 5.6 | **14.2** | **20.9** | 30.3 |
| `GET /api/complaints` (search) | 5.0 | **14.3** | **22.4** | 23.2 |
| `GET /api/stats` | 5.9 | **16.7** | **22.0** | 22.9 |

Every read endpoint sits **under 25 ms at p95**. `/api/stats` computes status, type, priority and department breakdowns, SLA buckets, a 14-day trend and five KPIs in **16.7 ms median**.

Arabic full-text search costs essentially nothing over an unfiltered list (14.3 vs 14.2 ms median), because both are driven by the same indexed query path.

### 9.2 Write path

| Endpoint | min | **p50** | **p95** | max |
|---|---:|---:|---:|---:|
| `POST /api/complaints` | 19.3 | **28.8** | **46.6** | 47.2 |

Intake includes triage, duplicate scan against 30 days of same-type complaints, department routing, reference-number allocation and four audit events — **28.8 ms median**.

### 9.3 Assistant

| Endpoint | min | **p50** | **p95** | max |
|---|---:|---:|---:|---:|
| `POST /api/chat` | 3 446 | **4 812** | **6 741** | 9 807 |

**~4.8 s median**, two orders of magnitude slower than every other endpoint. This is local LLM inference on CPU-class hardware and is the dominant cost in the system.

### 9.4 The architectural consequence

This measured gap is why **priority is assigned by deterministic rules at intake, not by the model**. Had the model been on the critical path, the citizen's confirmation would take ~4.8 s instead of ~29 ms — a **167× penalty** on the one interaction where the platform promises an immediate reference number.

The model still reviews the priority, but on a background worker after the response is sent. The test suite asserts this directly: *"submission stays off the model's critical path (< 1.5 s)"*.

---

## 10. Test suite coverage

**134 automated checks, 134 passing, 0 failing.** Run against a throwaway database so no test touches real data.

| Section | Checks | What it establishes |
|---|---:|---|
| Archive | 22 | Legal transitions, terminal-state guards, filter isolation, stats integrity |
| Listing, filtering, search | 16 | Multi-value filters, Arabic search, phone normalisation, pagination, sort whitelist |
| Automatic priority escalation | 14 | Per-SLA escalation, no-cascade guarantee, inquiry cap, idempotence |
| Auto-classification and routing | 12 | Type inference and department assignment across categories |
| Dashboard statistics | 11 | KPI arithmetic, percentages summing to 100, zero-filled trend |
| Meta | 10 | Vocabulary completeness, bilingual labels, routing totality |
| Workflow and history | 10 | Status transitions, illegal-transition rejection, audit trail |
| AI priority review | 6 | Model review runs off the critical path, writes no noise events |
| Public tracking | 5 | Contact details withheld, case-insensitive lookup |
| Attachments | 4 | Count limit, type whitelist, disk cleanup |
| Deletion | 4 | Cascade, orphan prevention |
| Detailed location | 4 | Optional field handling |
| Duplicate detection | 4 | Threshold behaviour, self-exclusion |
| Explicit override beats inference | 4 | Citizen's category choice wins, disagreement logged |
| Multipart creation | 3 | Form-data intake with files |
| Validation | 3 | Field-level rejection |
| Manual re-routing | 2 | Department change with audit trail |

Plus **34 retrieval assertions** (`test_retrieval.py`) and a live smoke suite (`test_live.py`).

### 10.1 Input validation — verified by execution

All six cases return **HTTP 422** with a field-level Arabic message:

| Field | Input | Result |
|---|---|:--:|
| Name | `ا` (1 char) | 422 |
| Phone | `0955abc123` | 422 |
| Description | `مشكلة` (5 chars) | 422 |
| Title | `خط` (2 chars) | 422 |
| Email | `abc@` | 422 |
| Name | empty | 422 |

Unknown reference `MOCT-2026-999999` → **404**.

### 10.2 Data integrity after the full benchmark

The evaluation created 25 complaints and deleted them again. Post-run state:

| Check | Result |
|---|---|
| Complaint count | 24 (unchanged from pre-run) |
| Benchmark rows remaining | 0 |
| Orphaned events | **0** |
| Reference numbers cited in the demo file | 4 / 4 present |

---

## 11. Known defects and limitations

Reported as found, in severity order.

### 11.1 Attachment size limit contradicts the documentation

| Source | Stated limit |
|---|---:|
| `services.py` (enforced) | **10 MB** |
| `docs/knowledge-base.md` (6 places) | **5 MB** |

The assistant repeats the documented figure, so **citizens are told a limit half the enforced one**. Impact: a citizen with a 7 MB file is told it will be rejected when it would be accepted. Fix: pick one number and align both. Not applied — which figure is authoritative is a policy decision.

### 11.2 One out-of-scope question was not declined

"What is the weather tomorrow?" returned platform content about SLA escalation instead of a refusal. 2 of 3 out-of-scope questions were handled correctly.

Root cause: `MIN_SCORE = 0.012` is low enough that incidental term overlap clears it, so the model receives passages and treats them as answerable. Candidate fixes: raise `MIN_SCORE`, or add a relevance check between retrieval and generation. Not applied — raising the floor risks refusing legitimate questions, and that trade-off needs a larger question set to calibrate safely.

### 11.3 Duplicate threshold is not optimally placed

0.72 sits in a completely flat region (0.50–0.84 give identical results). 0.86 achieves F1 = 1.000 on the test set. See §6.3. Not applied — 14 pairs is too small a basis for retuning a deployed constant.

### 11.4 Retrieval ranking error observed outside the formal set

The question «ما هي أنواع الشكاوى؟» ("what are the complaint types?") returned a complete, well-formed answer about **duplicate detection**. hit@3 is 100 % on the labelled set, so this is a ranking weakness on phrasings not represented there — evidence that 34 questions is not enough to characterise retrieval fully.

### 11.5 Type classification collides on mixed vocabulary

Both type errors (§3.3) occur where a complaint legitimately contains vocabulary from two categories. Keyword scoring has no way to weigh which signal is central. Mitigated in the product rather than the model: the citizen's own choice always wins, and disagreement is logged for one-click reclassification.

### 11.6 Not measured

No concurrency or load testing; no authentication (the admin dashboard is unauthenticated by design for the demo); no accessibility audit; no cross-browser matrix; no formal frontend test suite. The database holds 24 complaints — query plans are not exercised at realistic volume.

---

## 12. Summary scorecard

| Capability | Metric | Result | Basis |
|---|---|---:|---|
| Type classification | Accuracy / Macro-F1 | **96.7 % / 0.966** | 60 labelled complaints |
| Routing | Accuracy | **96.7 %** | derived from type |
| Priority assignment | Accuracy / Macro-F1 | **90.0 % / 0.882** | 60 complaints, impact rubric |
| Priority — urgent recall | Recall (High) | **0.929** | 14 High-priority cases |
| Duplicate detection | Precision / Recall / F1 | **0.857 / 1.000 / 0.923** | 14 pairs incl. 8 hard negatives |
| Retrieval | hit@1 / hit@3 | **73.5 % / 100 %** | 34 bilingual questions |
| Retrieval — hybrid gain | hit@1 vs best single | **+11.7 pts** | same question set |
| Answer groundedness | In-scope | **15 / 15** | 18 assistant questions |
| Answer completeness | In-scope | **15 / 15** | after prompt fix |
| Language matching | Both directions | **18 / 18** | Arabic and English |
| Out-of-scope refusal | Correct | **2 / 3** | 3 off-topic questions |
| Read latency | p95 | **≤ 25 ms** | 30 samples/endpoint |
| Intake latency | p50 / p95 | **28.8 / 46.6 ms** | 25 samples |
| Assistant latency | p50 | **4.8 s** | 18 samples |
| Automated tests | Pass rate | **134 / 134** | full suite |
| Data integrity | Orphaned records | **0** | post-benchmark audit |

### What the numbers support

**Triage is production-plausible.** 96.7 % type accuracy with 8 of 12 categories perfect, and both errors of a kind a reviewing officer fixes in one click. Priority errors lean 4:2 toward over- rather than under-escalation, which is the right bias for public service.

**The hybrid retriever earns its complexity.** +11.7 points at hit@1 over the better single retriever, and 100 % hit@3 — measured, not assumed. This is the kind of claim that is usually asserted without evidence.

**The architecture is validated by its own latency numbers.** The 167× gap between rule-based intake (29 ms) and model inference (4.8 s) is precisely why the model sits off the critical path. That is a measured justification, not a design preference.

### What the numbers do not support

- Any claim about behaviour under concurrent load.
- Any claim that the assistant reliably refuses out-of-scope questions — it is 2 of 3.
- Any claim of correctness at data volumes beyond 24 complaints.
- Tight confidence intervals on any figure here. Every test set is small enough that a handful of cases moves the result.

---

<div align="center">

*Generated 2026-08-28 — all figures reproducible from the scripts described in §1.*

</div>
