"""Retrieval quality check for the knowledge base.

Run:  python test_retrieval.py

Answers two questions with evidence rather than assumption:

  1. Does the retriever actually find the section that answers each question?
  2. Does hybrid search beat either half on its own — i.e. does the extra
     machinery earn its place?

It scores sparse-only, dense-only and hybrid over the same question set, in
both languages, and reports hit@1 and hit@3. Requires the index to be built
(`python ingest.py`) and Ollama to be running.
"""

import sys

from app.ai import config, ollama
from app.ai.store import (RRF_K, WEIGHT_DENSE, WEIGHT_SPARSE, store,
                          tokenize)

# question -> substrings, any one of which is an acceptable chunk title.
# Several questions are answered equally well by their topic section or by
# the FAQ entry that restates it, so both count as a hit.
CASES: list[tuple[str, tuple[str, ...]]] = [
    # --- Arabic -----------------------------------------------------------
    ("كم تستغرق معالجة الشكوى؟", ("أسئلة شائعة",)),
    ("ما هي مهلة الأولوية العالية؟", ("الأولوية",)),
    ("لماذا شكواي أولويتها منخفضة؟", ("الأولوية",)),
    ("هل ترتفع الأولوية إذا تأخرت الشكوى؟", ("الأولوية",)),
    ("ماذا تعني حالة قيد المعالجة؟", ("حالات الشكوى",)),
    ("ما معنى أن الشكوى مغلقة؟", ("حالات الشكوى",)),
    ("كيف أتتبع شكواي بالرقم المرجعي؟", ("الرقم المرجعي",)),
    ("نسيت الرقم المرجعي ماذا أفعل؟", ("أسئلة شائعة",)),
    ("كم عدد المرفقات المسموح بها؟", ("تقديم الشكوى",)),
    ("ما هي البيانات التي تجمعونها عني؟", ("السياسة",)),
    ("هل يستطيع أحد رؤية رقم هاتفي؟", ("السياسة", "أسئلة شائعة")),
    ("من يعالج شكوى الفواتير؟", ("التصنيفات والجهات",)),
    ("ما اختصاص مديرية التحول الرقمي؟", ("التصنيفات والجهات",)),
    ("كيف يعمل النظام؟", ("كيف يعمل النظام",)),
    ("ماذا يحدث بعد إرسال الشكوى؟", ("كيف ستُحل شكواك",)),
    ("ما هي الشكاوى المكررة؟", ("الشكاوى المكررة",)),
    ("هل يمكنني تعديل الشكوى بعد إرسالها؟", ("تقديم الشكوى",)),
    # --- English ----------------------------------------------------------
    ("How long does a complaint take?", ("Frequently Asked",)),
    ("What is the deadline for high priority?", ("Priority",)),
    ("Why is my complaint low priority?", ("Priority",)),
    ("Does priority increase if delayed?", ("Priority",)),
    ("What does In Progress mean?", ("Complaint Statuses",)),
    ("Can a closed complaint be reopened?", ("Complaint Statuses",)),
    ("How do I track my complaint?", ("Reference Number",)),
    ("I lost my reference number", ("Frequently Asked",)),
    ("How many files can I attach?", ("Filing a Complaint",)),
    ("What data do you collect about me?", ("Policy",)),
    ("Can someone see my phone number?", ("Policy", "Frequently Asked")),
    ("Who handles billing complaints?", ("Categories and Responsible",)),
    ("What does the cybersecurity authority do?", ("Categories and Responsible",)),
    ("How does the system work?", ("How the System Works",)),
    ("What happens after I submit?", ("How Your Complaint Gets Solved",)),
    ("What is a duplicate complaint?", ("Duplicate Complaints",)),
    ("Can I edit my complaint after submitting?", ("Filing a Complaint",)),
]


def rank_sparse(query: str, limit: int) -> list[str]:
    return store._sparse(query, limit)


def rank_dense(query: str, limit: int) -> list[str]:
    return store._dense(query, limit)


def rank_hybrid(query: str, limit: int) -> list[str]:
    return [h.id for h in store.search(query, k=limit)]


def titles_for(ids: list[str]) -> list[str]:
    by_id = {c.id: c for c in store._chunks}
    return [by_id[i].metadata.get("title", "") for i in ids if i in by_id]


def evaluate(name: str, ranker) -> tuple[int, int, list[str]]:
    hit1 = hit3 = 0
    misses = []
    for question, expected in CASES:
        titles = titles_for(ranker(question, 3))
        if titles and any(e in titles[0] for e in expected):
            hit1 += 1
        if any(e in t for t in titles for e in expected):
            hit3 += 1
        else:
            misses.append(f"{question}  (wanted {list(expected)}, got {titles[:2]})")
    return hit1, hit3, misses


def main() -> int:
    if not ollama.available():
        print(f"SKIP: Ollama unreachable at {config.OLLAMA_URL}")
        return 0
    if not store.ready:
        print("SKIP: index not built. Run `python ingest.py` first.")
        return 0

    total = len(CASES)
    print(f"{total} questions ({sum(1 for q, _ in CASES if any('؀' <= c <= 'ۿ' for c in q))} Arabic)")
    print(f"corpus: {store.count()} chunks")
    print(f"fusion: RRF k={RRF_K}, sparse x{WEIGHT_SPARSE}, dense x{WEIGHT_DENSE}\n")

    results = {}
    for name, ranker in (("sparse only (BM25)", rank_sparse),
                         ("dense only (vectors)", rank_dense),
                         ("hybrid (RRF)", rank_hybrid)):
        hit1, hit3, misses = evaluate(name, ranker)
        results[name] = (hit1, hit3, misses)
        print(f"  {name:<22} hit@1 {hit1:>2}/{total} ({hit1/total:5.1%})"
              f"   hit@3 {hit3:>2}/{total} ({hit3/total:5.1%})")

    hybrid1, hybrid3, hybrid_misses = results["hybrid (RRF)"]
    sparse1, sparse3, _ = results["sparse only (BM25)"]
    dense1, dense3, _ = results["dense only (vectors)"]

    print()
    if hybrid_misses:
        print("hybrid misses:")
        for miss in hybrid_misses:
            print(f"  - {miss}")
        print()

    ok = True
    def assert_(label, condition, detail=""):
        nonlocal ok
        print(f"  {'PASS' if condition else 'FAIL'}  {label}  {detail}")
        ok = ok and condition

    assert_("hybrid finds the right section for at least 90% of questions",
            hybrid3 / total >= 0.90, f"{hybrid3}/{total}")
    assert_("hybrid is at least as good as sparse alone", hybrid3 >= sparse3,
            f"{hybrid3} vs {sparse3}")
    assert_("hybrid beats dense alone", hybrid3 > dense3, f"{hybrid3} vs {dense3}")

    print(f"\n{'=' * 52}\n  {'retrieval OK' if ok else 'retrieval REGRESSED'}\n{'=' * 52}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
