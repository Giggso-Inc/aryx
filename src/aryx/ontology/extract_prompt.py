"""System prompt + JSON schema for the entity-extraction agent.

Split out of `ontology/extract.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero test patches against this module — confirmed via
grep.
"""
from __future__ import annotations

_SYSTEM_BASE = (
    "You extract entity mentions from document text for a domain-specific "
    "knowledge graph. For each mention return: "
    "(1) `type` — a singular PascalCase noun that names the REAL-WORLD CONCEPT "
    "being referenced. Use domain-specific types when warranted (Goal, Scope, "
    "Aim, Initiative, Capability, ValueProposition, CustomerSegment, "
    "Milestone, Metric, Feature, Risk, Pricing, MarketSegment, Strategy, "
    "Partner, Competitor, Dataset, KPI, RoadmapItem, etc.). Fall back to "
    "generic NER (Organization, Person, Product, Location, Date) ONLY when "
    "no domain-specific type fits. NEVER use generic words (Entity, Item, "
    "Thing, Concept). "
    "(2) `name` — the exact name as it literally appears in the text. "
    "(3) `attributes` — typed attributes (role, founded, value, owner, etc.). "
    "(4) `span` — a short verbatim excerpt from the text that contains the "
    "name word-for-word. "
    "Only emit a mention when the name appears word-for-word inside the span. "
    "Prefer rich domain types over generic NER. Prefer fewer high-confidence "
    "mentions over many uncertain ones."
)


def _system_prompt(context: str) -> str:
    """Prepend the workspace business context so extraction is domain-aware."""
    if not context.strip():
        return _SYSTEM_BASE
    return (
        f"WORKSPACE CONTEXT (what this knowledge graph is about):\n{context.strip()}\n\n"
        + _SYSTEM_BASE
        + "\n\nUse the workspace context above to decide which entity types "
        "matter. Pull domain-specific concepts (Goal, Scope, Aim, "
        "Initiative, Capability, etc.) when relevant — NOT just generic "
        "Organization/Person/Date."
    )

_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "name": {"type": "string"},
                    "attributes": {"type": "object", "additionalProperties": True},
                    "span": {"type": "string"},
                },
                "required": ["type", "name", "span"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["mentions"],
    "additionalProperties": False,
}
