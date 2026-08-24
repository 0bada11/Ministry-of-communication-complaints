"""Retrieval-augmented answering for the citizen chatbot.

The model is small, so the prompt does the heavy lifting: it is given the
retrieved passages and told, in both languages, that anything not in them is
out of scope. A government complaints assistant inventing a deadline or a
policy is worse than one saying "call 1556" — so refusal is the designed
behaviour whenever retrieval comes back empty.
"""

import logging

from . import config, ollama
from .chunker import detect_language
from .store import Hit, store

logger = logging.getLogger("moct.ai")

# Below this fused score the top hit is treated as "nothing relevant found".
# Calibrated against the retrieval eval: genuine matches score well above it,
# while an off-topic question produces only weak, incidental term overlap.
MIN_SCORE = 0.012

CONTACT = "1556"

SYSTEM_PROMPT = """You are the assistant for the Syrian Ministry of \
Communications and Information Technology complaints platform \
(منصة شكاوى وزارة الاتصالات وتقانة المعلومات).

You help citizens understand how to file, track and follow up a complaint.

ABSOLUTE RULES:
1. Answer ONLY from the passages given to you under CONTEXT. They are extracts \
from the official platform documentation.
2. If the CONTEXT does not contain the answer, say so plainly and point the \
citizen to the Citizen Service Centre on 1556. Never guess, never invent a \
number, a deadline, a department name or a procedure.
3. Reply in the SAME language the citizen used. Arabic question -> Arabic \
answer. English question -> English answer.
4. Be brief and direct: two to four sentences unless a list is genuinely \
clearer. Do not repeat the question back.
5. Quote exact figures from the CONTEXT when they answer the question \
(hours, limits, counts).
6. Never ask for or repeat personal data such as a phone number or national ID.
7. You cannot look up an individual complaint, check its status, or change \
anything. If asked to, explain that the citizen should use the "تتبع شكوى" \
box on the home page with their reference number.

Write naturally, as a helpful government service desk would."""

NO_CONTEXT_AR = (
    "لا تتوفر لديّ معلومة عن هذا الموضوع ضمن دليل المنصة. "
    f"للاستفسارات الأخرى يمكنك التواصل مع مركز خدمة المواطن على الرقم {CONTACT}."
)
NO_CONTEXT_EN = (
    "I don't have information on that in the platform's documentation. "
    f"For anything else, contact the Citizen Service Centre on {CONTACT}."
)

UNAVAILABLE_AR = (
    "المساعد الذكي غير متاح حالياً. يمكنك تصفّح الأسئلة الشائعة، "
    f"أو التواصل مع مركز خدمة المواطن على الرقم {CONTACT}."
)
UNAVAILABLE_EN = (
    "The assistant is unavailable right now. Please see the FAQ, "
    f"or contact the Citizen Service Centre on {CONTACT}."
)


def _build_prompt(
    question: str, hits: list[Hit], history: list[dict], language: str
) -> str:
    passages = "\n\n---\n\n".join(
        f"[{index + 1}] {hit.text}" for index, hit in enumerate(hits)
    )

    conversation = ""
    if history:
        # Only the last couple of turns: the model has a small context window
        # and older turns crowd out the retrieved passages, which matter more.
        lines = []
        for turn in history[-4:]:
            role = "Citizen" if turn.get("role") == "user" else "Assistant"
            content = (turn.get("content") or "").strip()[:400]
            if content:
                lines.append(f"{role}: {content}")
        if lines:
            conversation = "RECENT CONVERSATION:\n" + "\n".join(lines) + "\n\n"

    # Retrieval often hands back passages in the other language — an English
    # question with no English keyword match pulls Arabic chunks, and vice
    # versa — and the model then answers in the language of the context it was
    # given. Stating the required language outright is far more reliable than
    # asking it to infer one from the question.
    instruction = "أجب بالعربية فقط." if language == "ar" else "Answer in English only."

    return (
        f"{conversation}CONTEXT:\n{passages}\n\n"
        f"CITIZEN'S QUESTION:\n{question}\n\n"
        f"Answer using only the CONTEXT above. {instruction}"
    )


def answer(question: str, history: list[dict] | None = None) -> dict:
    """Answer a citizen question from the knowledge base.

    Always returns a usable reply. `grounded` says whether the answer came from
    retrieved passages; `sources` lists the sections it drew on.
    """
    question = (question or "").strip()
    language = detect_language(question)

    if not question:
        return {
            "answer": NO_CONTEXT_AR if language == "ar" else NO_CONTEXT_EN,
            "sources": [], "grounded": False, "available": True,
        }

    if not config.AI_ENABLED or not ollama.available():
        return {
            "answer": UNAVAILABLE_AR if language == "ar" else UNAVAILABLE_EN,
            "sources": [], "grounded": False, "available": False,
        }

    hits = store.search(question)
    hits = [h for h in hits if h.score >= MIN_SCORE]

    if not hits:
        # Refusing is correct here: there is nothing to ground an answer in.
        return {
            "answer": NO_CONTEXT_AR if language == "ar" else NO_CONTEXT_EN,
            "sources": [], "grounded": False, "available": True,
        }

    text = ollama.generate(
        _build_prompt(question, hits, history or [], language),
        system=SYSTEM_PROMPT,
        temperature=0.2,
        max_tokens=500,
    )

    if not text:
        return {
            "answer": UNAVAILABLE_AR if language == "ar" else UNAVAILABLE_EN,
            "sources": [], "grounded": False, "available": False,
        }

    # De-duplicate by section: three chunks from one section is one source to
    # a reader, not three.
    sources, seen = [], set()
    for hit in hits:
        title = hit.metadata.get("title", "")
        if title and title not in seen:
            seen.add(title)
            sources.append({"title": title, "lang": hit.metadata.get("lang", "")})

    return {"answer": text, "sources": sources, "grounded": True, "available": True}
