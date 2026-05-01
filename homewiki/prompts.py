"""Prompt construction for grounded Ask responses."""

from __future__ import annotations

from homewiki.schemas import SearchResult


ASK_SYSTEM_PROMPT = """You answer questions about a local home wiki.

Rules:
- Use only the provided home wiki evidence.
- Do not invent repair steps, warranty facts, phone numbers, or URLs.
- Prefer exact model numbers, error codes, source paths, and section titles.
- Cite source paths or filenames and sections in the answer.
- If the evidence is insufficient, say what information is missing.
- For safety-critical appliance issues, tell the user to check the source
  manual before acting.
- Keep local evidence separate from missing information.
"""


def build_ask_messages(
    question: str,
    evidence: list[SearchResult],
) -> list[dict[str, str]]:
    """Build OpenAI-compatible chat messages for a grounded answer."""

    return [
        {"role": "system", "content": ASK_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Question:\n{question.strip()}\n\n"
                f"Home wiki evidence:\n{format_evidence_for_prompt(evidence)}"
            ),
        },
    ]


def format_evidence_for_prompt(evidence: list[SearchResult]) -> str:
    """Render evidence with stable labels, source paths, sections, and text."""

    if not evidence:
        return "No evidence was retrieved."

    blocks: list[str] = []
    for index, result in enumerate(evidence, start=1):
        source = result.markdown_path or result.source_path
        section = result.section_title or "Unsectioned"
        asset = result.asset_id or "unknown asset"
        blocks.append(
            "\n".join(
                [
                    f"[{index}] Source: {source}",
                    f"    Section: {section}",
                    f"    Asset: {asset}",
                    f"    Text: {result.text}",
                ]
            )
        )
    return "\n\n".join(blocks)


__all__ = [
    "ASK_SYSTEM_PROMPT",
    "build_ask_messages",
    "format_evidence_for_prompt",
]
