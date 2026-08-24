"""Split the knowledge base into retrievable chunks.

The document was written with retrieval in mind: `## N. Title` sections that
each stand alone, a keyword line per section, and parallel Arabic and English
halves. The chunker preserves that structure rather than cutting at a fixed
character count, which would slice tables in half and separate a question from
its answer.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# A section longer than this is split further, but only along its own internal
# boundaries — never mid-table and never mid-answer.
MAX_CHUNK_CHARS = 1400

_ARABIC = re.compile(r"[؀-ۿ]")


def detect_language(text: str) -> str:
    """`ar` when the text is meaningfully Arabic, else `en`.

    Counted rather than merely detected: the English half quotes Arabic labels
    throughout, so a single Arabic character cannot be the deciding vote.
    """
    arabic = len(_ARABIC.findall(text))
    letters = sum(1 for c in text if c.isalpha())
    return "ar" if letters and arabic / letters > 0.35 else "en"


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)


def _split_faq(body: str) -> list[str]:
    """One chunk per question, so a match returns that answer and not twelve."""
    parts = re.split(r"\n(?=\*\*(?:س|Q):)", body)
    return [p.strip() for p in parts if p.strip()]


def _split_long(body: str) -> list[str]:
    """Break an oversized section on its own subheadings, then on blank lines.

    Markdown tables are kept whole: a table split across chunks loses its
    header row and stops being answerable.
    """
    if "###" in body:
        parts = re.split(r"\n(?=###\s)", body)
    else:
        parts = re.split(r"\n\s*\n(?!\|)", body)

    merged: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Glue small fragments together rather than emitting a chunk per line.
        if merged and len(merged[-1]) + len(part) < MAX_CHUNK_CHARS:
            merged[-1] = f"{merged[-1]}\n\n{part}"
        else:
            merged.append(part)
    return merged


def chunk_markdown(path: Path) -> list[Chunk]:
    """Turn the knowledge base into chunks tagged with language and section."""
    raw = path.read_text(encoding="utf-8")

    # Drop the YAML front matter — it is metadata for humans, not an answer.
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            raw = raw[end + 4:]

    chunks: list[Chunk] = []
    part_title = ""

    # Split on level-1 headings first so each chunk knows which half it is in.
    for part in re.split(r"\n(?=#\s)", raw):
        heading_match = re.match(r"#\s+(.+)", part.strip())
        if heading_match and not part.strip().startswith("##"):
            part_title = heading_match.group(1).strip()

        for section in re.split(r"\n(?=##\s)", part):
            section = section.strip()
            if not section or section.startswith("# "):
                continue

            title_match = re.match(r"##\s+(.+)", section)
            if not title_match:
                continue
            title = title_match.group(1).strip()
            body = section[title_match.end():].strip()
            if not body:
                continue

            language = detect_language(section)
            is_faq = "أسئلة شائعة" in title or "Frequently Asked" in title

            if is_faq:
                bodies = _split_faq(body)
            elif len(body) > MAX_CHUNK_CHARS:
                bodies = _split_long(body)
            else:
                bodies = [body]

            for index, piece in enumerate(bodies):
                # Every chunk carries its own heading. Retrieval returns the
                # chunk alone, so it has to say what it is about without
                # relying on a neighbour for context.
                text = f"## {title}\n\n{piece}"
                chunks.append(Chunk(
                    id=f"{language}-{_slug(title)}-{index}",
                    text=text,
                    metadata={
                        "lang": language,
                        "title": title,
                        "part": part_title,
                        "section_index": index,
                    },
                ))
    return chunks


def _slug(title: str) -> str:
    cleaned = re.sub(r"[^\w؀-ۿ]+", "-", title).strip("-")
    return cleaned[:60] or "section"
