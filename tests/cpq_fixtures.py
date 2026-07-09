"""Ground-truth derivation for the CPQ end-to-end scenarios (S1–S7).

Zero-hardcoding contract: every expectation is computed at runtime from
whatever BigMachines ``bm_config_zip_cache`` XML export is supplied — no
entity names, ids, counts, variable names, or menu values from any specific
sample file may appear as literals in test code. The sample path comes from
the ``ARYX_CPQ_SAMPLE`` env var (default: ``SL3500e_Dummy_Config.xml`` at the
repo root); any other customer export drops in without test changes.

The parsing here mirrors the semantics of ``doc_discovery`` (entity elements,
locale containers) but is kept independent so the tests are a second opinion
on extraction, not a tautology.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Locale wrapper tags — multilingual value containers, not entity types.
# Mirrors doc_discovery._LOCALE_TAGS.
LOCALE_TAGS = frozenset({
    "en", "de", "fr", "es", "it", "da", "nl", "sv", "no", "fi", "pl", "cs",
    "ru", "tr", "ar", "he", "ja", "ko", "zh", "pt",
    "ja_JP", "zh_CN", "zh_HK", "zh_TW", "zh_SG", "ko_KR", "da_DK",
    "pt_BR", "pt_PT", "fr_CA", "es_CO",
})


def sample_path() -> Path:
    """Resolve the sample XML path (env-configurable, never hardcoded in tests)."""
    return Path(os.environ.get(
        "ARYX_CPQ_SAMPLE", str(REPO_ROOT / "SL3500e_Dummy_Config.xml")))


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _is_container(tag: str) -> bool:
    return tag.startswith("_") or tag in LOCALE_TAGS


def _is_entity(elem: ET.Element) -> bool:
    """Entity detection matching doc_discovery: ≥2 distinct non-container
    child tags, or attribute-only leaves."""
    child_tags = {_strip_ns(c.tag) for c in elem if not _is_container(_strip_ns(c.tag))}
    if child_tags:
        return len(child_tags) >= 2
    return len(elem.attrib) >= 1


def _scalar(elem: ET.Element) -> str | None:
    """Extract the scalar value of a leaf/locale-wrapped field element."""
    sub = list(elem)
    if sub:
        tags = {_strip_ns(c.tag) for c in sub}
        if tags & LOCALE_TAGS:
            en = next((c for c in sub if _strip_ns(c.tag) == "en"), None)
            if en is not None and en.text and en.text.strip():
                return en.text.strip()
            for c in sub:
                if c.text and c.text.strip():
                    return c.text.strip()
        return None
    return elem.text.strip() if elem.text and elem.text.strip() else None


def entity_fields(elem: ET.Element) -> dict[str, str]:
    """Scalar field map for an entity element (attributes + child leaves)."""
    fields: dict[str, str] = dict(elem.attrib)
    for child in elem:
        tag = _strip_ns(child.tag)
        if _is_container(tag):
            continue
        val = _scalar(child)
        if val is not None:
            fields[tag] = val
    return fields


@dataclass
class SampleTruth:
    """Everything the scenarios need, derived from one XML export."""

    path: Path
    # element tag → count of entity elements of that tag
    entity_counts: Counter = field(default_factory=Counter)
    # element tag → list of scalar field dicts (one per entity element)
    entities: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    # ── derived views ────────────────────────────────────────────────────────

    def tags_matching(self, suffix: str) -> list[str]:
        """Entity tags whose normalized name ends with suffix (e.g. 'config_rule')."""
        norm = suffix.lower().replace("_", "")
        return [t for t in self.entities
                if t.lower().replace("_", "").endswith(norm)]

    def rows(self, suffix: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for t in self.tags_matching(suffix):
            out.extend(self.entities[t])
        return out

    def rules(self) -> list[dict[str, str]]:
        return [r for r in self.rows("config_rule") if "rule_type" in r]

    def rule_inputs(self) -> list[dict[str, str]]:
        return self.rows("config_rule_input")

    def rule_actions(self) -> list[dict[str, str]]:
        return self.rows("config_rule_action")

    def functions(self) -> list[dict[str, str]]:
        return [r for r in self.rows("function") if r.get("script_text")]

    def config_attrs(self) -> list[dict[str, str]]:
        return [r for r in self.rows("config_attr") if r.get("variable_name")]

    def menu_items(self) -> list[dict[str, str]]:
        return self.rows("menu_item")

    def script_backed_rules(self) -> list[dict[str, str]]:
        """Rules whose condition or any action references a BML function."""
        rules_with_scripts: list[dict[str, str]] = []
        action_fn_by_rule: dict[str, bool] = {}
        for act in self.rule_actions():
            fn = act.get("function_id", "-1")
            if fn not in ("", "-1"):
                action_fn_by_rule[act.get("bm_config_rule_id", "")] = True
        for rule in self.rules():
            cond_fn = rule.get("condition_function_id", "-1")
            if cond_fn not in ("", "-1") or action_fn_by_rule.get(rule.get("id", "")):
                rules_with_scripts.append(rule)
        return rules_with_scripts


def load_truth(path: Path | None = None) -> SampleTruth:
    """Parse the sample export into ground truth. Pure — no Aryx imports."""
    p = path or sample_path()
    truth = SampleTruth(path=p)
    root = ET.parse(p).getroot()

    def walk(elem: ET.Element) -> None:
        for child in elem:
            tag = _strip_ns(child.tag)
            if _is_container(tag):
                walk(child)
                continue
            if _is_entity(child):
                truth.entity_counts[tag] += 1
                truth.entities.setdefault(tag, []).append(entity_fields(child))
            walk(child)

    walk(root)
    return truth
