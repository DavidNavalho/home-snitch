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


INDUSTRIAL_ASK_SYSTEM_PROMPT = """You answer questions for a factory floor knowledge base of industrial equipment manuals.

Rules:
- Use only the provided equipment manual evidence.
- Prefer exact fault codes, model numbers, parameter numbers, terminal labels, and section titles.
- Cite source paths or filenames and sections in the answer.
- For procedures, list steps in order with the cited section per step.
- For safety-critical actions (electrical work, rotating machinery, pressurized systems, hot surfaces) explicitly require:
  de-energize / lockout-tagout, verify zero energy, wear required PPE, and reference the cited safety section before acting.
- If the evidence is insufficient, say what information is missing (e.g. wiring diagram section, parameter list).
- Keep local evidence separate from missing information.
"""


def build_ask_messages(
    question: str,
    evidence: list[SearchResult],
    *,
    domain_mode: str = "home",
) -> list[dict[str, str]]:
    """Build OpenAI-compatible chat messages for a grounded answer."""

    if domain_mode == "industrial":
        system = INDUSTRIAL_ASK_SYSTEM_PROMPT
        evidence_label = "Equipment manual evidence"
    else:
        system = ASK_SYSTEM_PROMPT
        evidence_label = "Home wiki evidence"

    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"Question:\n{question.strip()}\n\n"
                f"{evidence_label}:\n{format_evidence_for_prompt(evidence)}"
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
    "INDUSTRIAL_ASK_SYSTEM_PROMPT",
    "build_ask_messages",
    "format_evidence_for_prompt",
]
