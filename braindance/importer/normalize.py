"""Turn upstream card records into `Card` objects.

Design rule: parse loudly. Anything this module does not recognise is reported in
`PoolStats` rather than silently dropped or guessed at. New sets will introduce new
tokens, and a silent miss in the card pool corrupts every downstream number.
"""

from __future__ import annotations

import re

from .schema import (
    Card,
    CardType,
    Color,
    StreetCredCondition,
    StreetCredKind,
    Trigger,
)

#: Upstream uses U+2606 (☆) almost everywhere but U+2605 (★) on at least one card.
#: Collapse them before any matching.
_STAR_VARIANTS = "☆★"
_STAR = "☆"

#: "(Street Cred)" is reminder text glossing the ☆ symbol. Removing it first keeps the
#: condition patterns readable.
_STREET_CRED_GLOSS = re.compile(r"\s*\(\s*Street\s*Cred\s*\)")

_BRACE_TOKEN = re.compile(r"\{([^}]+)\}")
_PARENTHETICAL = re.compile(r"\([^()]*\)")

_TRIGGERS_BY_TEXT = {t.value.casefold(): t for t in Trigger}

# Ordered most-specific first. Each entry is (kind, pattern, value_group).
_STREET_CRED_PATTERNS: list[tuple[StreetCredKind, re.Pattern[str], int | None]] = [
    (
        StreetCredKind.ABSOLUTE_LESS_THAN,
        re.compile(rf"less\s+than\s+(\d+)\s*{_STAR}", re.I),
        1,
    ),
    (
        StreetCredKind.RIVAL_DIFFERS_BY,
        re.compile(rf"{_STAR}\s+differs\s+from\s+a\s+Rival'?s?\s+by\s+(\d+)\+?", re.I),
        1,
    ),
    (
        StreetCredKind.PARITY_EVEN,
        re.compile(rf"{_STAR}\s+is\s+an\s+even\s+number", re.I),
        None,
    ),
    (
        StreetCredKind.RIVAL_MORE,
        re.compile(rf"more\s+{_STAR}\s+than\s+a\s+Rival", re.I),
        None,
    ),
    (
        StreetCredKind.RIVAL_LESS,
        re.compile(rf"less\s+{_STAR}\s+than\s+a\s+Rival", re.I),
        None,
    ),
]


def normalize_stars(text: str) -> str:
    """Collapse Street Cred symbol variants to a single codepoint."""
    return re.sub(f"[{_STAR_VARIANTS}]", _STAR, text)


def split_name(display_name: str) -> tuple[str, str | None]:
    """Split "Evelyn Parker - Beautiful Enigma" into name and subtitle.

    CR 7.3.1 bans two Legends sharing a *name*, while CR 7.3.3 keys the 3-copy limit on
    the name+subtitle pair -- so this split is load-bearing for deck legality, not
    cosmetic. Splits on the first " - " only; subtitles may themselves contain dashes.
    """
    name, sep, subtitle = display_name.partition(" - ")
    if not sep:
        return display_name.strip(), None
    return name.strip(), subtitle.strip() or None


def strip_reminder_text(text: str) -> tuple[str, list[str]]:
    """Separate effect text from parenthetical reminder text.

    CR 3.18.1.2.2.1: reminder text does not influence gameplay. Interaction search that
    matches against reminder text will report combos that do not exist, because reminder
    text restates keywords the card merely *has*.

    Upstream carries no italics, so parenthesis is the only available signal. Both halves
    are retained; nothing is discarded.
    """
    reminders = [m.group(0)[1:-1].strip() for m in _PARENTHETICAL.finditer(text)]
    effect = _PARENTHETICAL.sub(" ", text)
    effect = re.sub(r"[ \t]{2,}", " ", effect)
    effect = re.sub(r"\n{2,}", "\n", effect)
    return effect.strip(), [r for r in reminders if r]


def parse_triggers(text: str) -> tuple[list[Trigger], list[str]]:
    """Extract brace-delimited triggers, preserving first-appearance order.

    Returns (triggers, unknown_tokens). Unknown tokens are surfaced rather than ignored
    so a new set's keyword shows up as a loud import warning.
    """
    found: list[Trigger] = []
    unknown: list[str] = []
    for match in _BRACE_TOKEN.finditer(text):
        token = match.group(1).strip()
        trigger = _TRIGGERS_BY_TEXT.get(token.casefold())
        if trigger is None:
            if token not in unknown:
                unknown.append(token)
        elif trigger not in found:
            found.append(trigger)
    return found, unknown


def parse_street_cred(text: str) -> tuple[list[StreetCredCondition], list[str]]:
    """Extract Street Cred predicates from card text.

    Upstream exposes `street_cred_requirement` as a nullable integer. It is null on every
    record, and could not represent these conditions even if populated: they include
    comparisons against the Rival and a parity check. Parity matters -- Street Cred is a
    sum of die faces, so it is a fair coin unless an effect adjusts a Gig by an odd
    amount.

    Returns (conditions, unparsed_clauses). Every ☆ in the text must be consumed by some
    pattern; any that is not is reported as an unparsed clause.
    """
    text = normalize_stars(text)
    stripped = _STREET_CRED_GLOSS.sub("", text)

    conditions: list[StreetCredCondition] = []
    covered: list[tuple[int, int]] = []

    for kind, pattern, value_group in _STREET_CRED_PATTERNS:
        for match in pattern.finditer(stripped):
            value = int(match.group(value_group)) if value_group else None
            conditions.append(
                StreetCredCondition(
                    kind=kind, value=value, source=match.group(0).strip()
                )
            )
            covered.append(match.span())

    unparsed = [
        clause
        for index in (m.start() for m in re.finditer(_STAR, stripped))
        if not any(start <= index < end for start, end in covered)
        for clause in (_clause_around(stripped, index),)
    ]
    return conditions, unparsed


def _clause_around(text: str, index: int) -> str:
    """Return the sentence containing `index`, for reporting an unparsed condition."""
    start = max(text.rfind(".", 0, index) + 1, text.rfind("\n", 0, index) + 1, 0)
    end_candidates = [p for p in (text.find(".", index), text.find("\n", index)) if p != -1]
    end = min(end_candidates) + 1 if end_candidates else len(text)
    return text[start:end].strip()


def normalize_card(raw: dict) -> tuple[Card, list[str], list[str]]:
    """Build a `Card` from one upstream record.

    Returns (card, unknown_brace_tokens, unparsed_street_cred_clauses).
    """
    raw_text = normalize_stars(raw.get("ability_text") or "")
    effect_text, reminders = strip_reminder_text(raw_text)

    # Triggers are parsed from the reminder-stripped text: a keyword's own reminder
    # gloss repeats the brace token and would otherwise double-count.
    triggers, unknown_tokens = parse_triggers(effect_text)
    street_cred, unparsed = parse_street_cred(raw_text)

    name, subtitle = split_name(raw["name"])

    card = Card(
        base_card_id=raw["base_card_id"],
        name=name,
        subtitle=subtitle,
        card_type=CardType(raw["card_type"]),
        color=Color(raw["color"]),
        eddie_cost=raw.get("eddie_cost"),
        ram_cost=raw.get("ram_cost"),
        ram_provided=raw.get("ram_provided"),
        power=raw.get("power"),
        has_sell_tag=bool(raw.get("has_sell_tag")),
        raw_ability_text=raw_text,
        effect_text=effect_text,
        reminder_text=reminders,
        triggers=triggers,
        street_cred=street_cred,
        classification=list(raw.get("classification") or []),
        set_name=raw.get("set_name") or "",
        set_code=raw.get("set_code") or "",
        card_number=raw.get("card_number") or "",
        rarity=raw.get("rarity"),
    )
    return card, unknown_tokens, unparsed
