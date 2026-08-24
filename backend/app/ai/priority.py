"""AI-assigned complaint priority.

The citizen no longer chooses a priority — the model reads the complaint and
decides. Two safeguards sit around that decision, because a 4B model running
on a laptop is not something a public service should trust unconditionally:

  1. **A safety floor.** If the wording contains an explicit emergency phrase
     (`مستشفى`, `انقطاع كامل`, `طارئ`, `emergency`…), the priority cannot come
     out below عالية no matter what the model says. A model that quietly
     demotes a hospital outage would be worse than no model.

  2. **A deterministic fallback.** If Ollama is unreachable, slow, or returns
     something that is not a valid priority, the existing rule-based classifier
     decides instead. Intake never fails because a local model is not running.

Every outcome records which of the three paths produced it, and that reasoning
is written to the complaint's update log.
"""

import logging

from ..classifier import keyword_priority, suggest_priority
from ..domain import LABELS, ComplaintType, Priority, SLA_HOURS
from . import config, ollama

logger = logging.getLogger("moct.ai")

SYSTEM_PROMPT = """You triage citizen complaints for the Syrian Ministry of \
Communications and Information Technology. You assign one priority to each \
complaint. You are given the complaint text; nothing else about the citizen \
matters.

PRIORITY LEVELS — assign exactly one:

"high"   — Service is completely down, or the problem is dangerous, or it \
affects critical facilities (hospitals, emergency services, water, power), or \
it affects a whole area or many people, or it is a security incident \
(data breach, hacking, fraud), or the citizen reports it has already been \
ignored or is recurring over a long period. Target resolution: 24 hours.

"medium" — A real fault or billing error affecting one subscriber, degrading \
service but not stopping it entirely. This is the default for genuine problems. \
Target resolution: 72 hours.

"low"    — A question, an information request, a suggestion, or a routine \
administrative request such as transferring a line. Nothing is broken. \
Target resolution: 120 hours.

RULES:
- Judge only the severity and urgency described. Ignore politeness, anger, \
insistence, ALL CAPS or threats — an angry tone about a simple question is \
still "low".
- The complaint may be in Arabic or English. Treat both identically.
- Do not inflate. Most genuine faults are "medium".
- Reply with JSON only: {"priority": "high|medium|low", "reason": "<short \
justification in the complaint's own language, max 15 words>"}"""


def _build_prompt(title: str, description: str, ctype: ComplaintType) -> str:
    label = LABELS["type"][ctype]
    return (
        f"CATEGORY: {label['en']} / {label['ar']}\n"
        f"TITLE: {title}\n"
        f"DESCRIPTION: {description}\n\n"
        "Assign the priority."
    )


def decide(title: str, description: str, ctype: ComplaintType) -> dict:
    """Choose a priority for a complaint.

    Returns `priority`, `source` (`ai`, `ai+floor`, or `rules`), and `reason`
    — a short human-readable justification for the update log.
    """
    text = f"{title} {description}"
    fallback = suggest_priority(text, ctype)

    # The emergency floor is computed from the wording regardless of which path
    # ends up deciding, so it applies to the model and the rules alike.
    matched = keyword_priority(text)
    floor = matched[0] if matched and matched[0] is Priority.HIGH else None

    if not config.AI_ENABLED or not ollama.available():
        return {
            "priority": fallback,
            "source": "rules",
            "reason": "تحديد تلقائي حسب قواعد التصنيف (المساعد الذكي غير متاح)",
        }

    payload = ollama.generate_json(
        _build_prompt(title, description, ctype),
        system=SYSTEM_PROMPT,
        temperature=0.0,
        max_tokens=160,
    )

    raw = (payload or {}).get("priority")
    try:
        chosen = Priority(str(raw).strip().lower())
    except (ValueError, AttributeError):
        if payload is not None:
            logger.warning("model returned an unusable priority: %r", raw)
        return {
            "priority": fallback,
            "source": "rules",
            "reason": "تحديد تلقائي حسب قواعد التصنيف",
        }

    reason = (payload.get("reason") or "").strip()[:160]

    if floor and chosen is not Priority.HIGH:
        # The model tried to go below an explicit emergency signal. Overrule it
        # and say so, rather than silently accepting the downgrade.
        logger.info("priority floor applied: model said %s, keyword %r forces high",
                    chosen.value, matched[1])
        return {
            "priority": Priority.HIGH,
            "source": "ai+floor",
            "reason": f"رُفعت إلى «عالية» لورود عبارة «{matched[1]}» في الوصف",
        }

    return {
        "priority": chosen,
        "source": "ai",
        "reason": reason or "تحديد آلي بناءً على وصف المشكلة",
    }


def describe(result: dict) -> str:
    """The note written to the complaint's update log.

    The Arabic prefix is built here rather than asked of the model, so the
    facts staff act on — who decided, which level, what deadline — are always
    Arabic and always correctly formatted. gemma3:4b ignores the prompt's
    request to write its justification in Arabic and answers in English; that
    text is supplementary, so it is appended as-is rather than fought over.
    """
    label = LABELS["priority"][result["priority"]]["ar"]
    hours = SLA_HOURS[result["priority"]]
    origin = {
        "ai": f"تحديد آلي بالذكاء الاصطناعي ({config.LLM_MODEL})",
        "ai+floor": "تحديد آلي مع تطبيق حد الطوارئ",
        "rules": "تحديد بقواعد التصنيف",
    }[result["source"]]
    return f"{origin} — «{label}»، مهلة {hours} ساعة. {result['reason']}"
