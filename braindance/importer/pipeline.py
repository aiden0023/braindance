"""Resolve raw upstream records into a single authoritative card pool.

The hard part is not parsing, it's *choosing*. Upstream ships 520 records covering only
~153 distinct cards, spread across Alpha, Beta, Retail, promo and demo printings -- and
49 of those cards have materially different rules text between printings. Deduplicating
carelessly mixes errata into the pool, which quietly poisons every downstream number.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .normalize import normalize_card, normalize_stars, strip_reminder_text
from .schema import Card, CardPool, PoolStats
from .sources import FetchResult

#: Printings that make up the launch-legal pool. Promo, demo, Alpha and Beta printings
#: are excluded: they are not the competitive pool.
RETAIL_MARKER = "Retail"

_BRACES = re.compile(r"[{}]")
_PUNCT = re.compile(r"[^a-z0-9+]+")


def is_retail(record: dict) -> bool:
    return RETAIL_MARKER in (record.get("set_name") or "")


def comparable_text(text: str) -> str:
    """Reduce rules text to its semantic content, for errata comparison.

    Early printings wrote timing triggers as bare capitals ("PLAY") where retail uses
    braces ("{Play}"), and reminder text was added and reworded throughout. Comparing raw
    strings therefore flags dozens of cards that never actually changed. This strips the
    presentation layer so a diff means a genuine rules change.
    """
    effect, _ = strip_reminder_text(normalize_stars(text))
    return _PUNCT.sub(" ", _BRACES.sub("", effect).casefold()).strip()


def _printing_rank(record: dict) -> tuple[int, int, str]:
    """Sort key choosing between multiple retail printings of the same card.

    Prefer the current printing, then the default printing, then a stable tiebreak so
    repeated imports of unchanged data produce identical pools.
    """
    return (
        0 if record.get("is_current") else 1,
        0 if record.get("is_default_printing") else 1,
        str(record.get("id") or ""),
    )


def resolve_pool(fetched: FetchResult) -> CardPool:
    """Build a validated `CardPool` from fetched records."""
    by_base: dict[str, list[dict]] = defaultdict(list)
    for record in fetched.records:
        base_id = record.get("base_card_id")
        if base_id:
            by_base[base_id].append(record)

    cards: list[Card] = []
    dropped: list[str] = []
    errata: list[str] = []
    formatting_only = 0
    duplicates_collapsed = 0
    unknown_tokens: list[str] = []
    unparsed_clauses: list[str] = []

    for base_id in sorted(by_base):
        printings = by_base[base_id]
        retail = [r for r in printings if is_retail(r)]
        if not retail:
            dropped.append(base_id)
            continue

        retail.sort(key=_printing_rank)
        chosen = retail[0]
        duplicates_collapsed += len(retail) - 1

        card, tokens, unparsed = normalize_card(chosen)

        # Errata is judged across *all* printings, not just retail: knowing a card was
        # reworded since Beta is exactly what a player brewing from old lists needs.
        # Only substantive changes count -- reformatting is not errata.
        variants = {comparable_text(r.get("ability_text") or "") for r in printings}
        if len(variants) > 1:
            card.has_errata = True
            errata.append(card.full_name)
        elif len({normalize_stars(r.get("ability_text") or "").strip() for r in printings}) > 1:
            formatting_only += 1

        cards.append(card)
        unknown_tokens.extend(t for t in tokens if t not in unknown_tokens)
        unparsed_clauses.extend(unparsed)

    cards.sort(key=lambda c: (c.card_type.value, c.color.value, c.full_name))

    stats = PoolStats(
        total_upstream_records=len(fetched.records),
        resolved_cards=len(cards),
        dropped_no_retail_printing=sorted(dropped),
        duplicate_records_collapsed=duplicates_collapsed,
        cards_with_errata=sorted(errata),
        cards_reformatted_only=formatting_only,
        unparsed_street_cred_clauses=unparsed_clauses,
        unknown_brace_tokens=unknown_tokens,
    )
    return CardPool(
        cards=cards,
        stats=stats,
        source=fetched.source,
        fetched_at=fetched.fetched_at,
    )


def errata_report(fetched: FetchResult) -> dict[str, dict[str, str]]:
    """Map card name -> {set_name: rules text} for cards whose text changed.

    Surfaced by `braindance import --diff`. Useful both as a data-quality check and as a
    genuine player-facing artefact.
    """
    by_base: dict[str, list[dict]] = defaultdict(list)
    for record in fetched.records:
        base_id = record.get("base_card_id")
        if base_id:
            by_base[base_id].append(record)

    report: dict[str, dict[str, str]] = {}
    for base_id, printings in sorted(by_base.items()):
        if len({comparable_text(r.get("ability_text") or "") for r in printings}) <= 1:
            continue  # reformatted only, not a rules change
        texts = {
            (r.get("set_name") or "?"): normalize_stars(r.get("ability_text") or "").strip()
            for r in printings
        }
        display = printings[0].get("name") or base_id
        report[display] = texts
    return report
