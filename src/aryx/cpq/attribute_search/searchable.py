"""Which configuration attributes an attribute search can match, and how values match.

- Attributes with menu options: the value is matched against the options.
- Yes/no attributes (no menu, or a menu of only yes/no options): a family
  "offers" one when it has the attribute; the value can only be a yes/no word.
- Internal yes/no flags are left out: "Is ..." predicates ("Is Item Type ...",
  camel-case "isRelatedService..."), "... Flag" labels and single-token names
  ("BoolContinue1", "Edit") -- checked on workspace 704, 2026-10-02.
  Acronym-led labels ("ISM Band Support", "ISDN Line Required") are real
  features and stay searchable (PR #423 review). A menu of
  yes/no options is a real customer-facing question, so it is never filtered.
- Hidden attributes are never searchable: they aren't offered to the customer.
"""
from __future__ import annotations

import re
from typing import Any

_YES = frozenset({"yes", "y", "true", "1", "on", "enable", "enabled", "with", "include", "included"})
_NO = frozenset({"no", "n", "false", "0", "off", "disable", "disabled", "without", "exclude",
                 "excluded"})

# One searchable attribute: (display_label, variable_name, options, is_boolean,
# select_type). A yes/no menu keeps its options so its Yes/No code is known.
Entry = tuple[str, str, list[Any], bool, str]


def _is_yes_no_options(options: list[Any]) -> bool:
    """True when every option is a yes/no word (e.g. Yes / No)."""
    words = _YES | _NO
    return bool(options) and all(
        o.item_value.strip().casefold() in words or o.display_name.strip().casefold() in words
        for o in options
    )


def _looks_like_feature(label: str) -> bool:
    """A customer-facing yes/no label, not an internal flag name."""
    words = label.strip().split()
    if len(words) < 2 or words[-1].casefold() == "flag":
        return False
    first = words[0]
    return first.casefold() != "is" and not re.match(r"is[A-Z]", first)


def searchable_entry(attr: Any) -> Entry | None:
    """The searchable form of a ConfigAttr, or None when it isn't searchable."""
    if attr.hidden:
        return None
    base = (attr.display_label, attr.variable_name, list(attr.options))
    if _is_yes_no_options(attr.options):
        return (*base, True, attr.select_type)
    if attr.select_type == "boolean":
        if not _looks_like_feature(attr.display_label):
            return None
        return (*base, True, attr.select_type)
    if not attr.options:
        return None
    return (*base, False, attr.select_type)


def boolean_code(options: list[Any], answer: str) -> str | None:
    """The code to store for a yes/no answer ("Yes"/"No").

    A yes/no menu stores its matching option's item_value (e.g. "YES"); a
    true boolean attribute stores "true"/"false", as the engine does.
    """
    if not options:
        return "true" if answer == "Yes" else "false"
    words = _YES if answer == "Yes" else _NO
    for o in options:
        if o.item_value.strip().casefold() in words or o.display_name.strip().casefold() in words:
            return o.item_value
    return None


def yes_no(value: str | None) -> str | None:
    """"Yes" for no value or a yes word, "No" for a no word, else None."""
    word = (value or "").strip().casefold()
    if not word or word in _YES:
        return "Yes"
    if word in _NO:
        return "No"
    return None


def option_matches(option: Any, spellings: list[str]) -> bool:
    """True when any spelling appears as a whole word in the option's value or label."""
    text = f"{option.item_value} {option.display_name}".casefold()
    for spelling in spellings:
        pattern = r"(?<![0-9a-z])" + re.escape(spelling.casefold()) + r"(?![0-9a-z])"
        if re.search(pattern, text):
            return True
    return False
