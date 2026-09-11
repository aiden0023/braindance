"""Pool resolution tests -- the printing-selection logic.

These cover the failure mode that matters most: quietly mixing errata from an old
printing into the launch-legal pool.
"""

from __future__ import annotations

import pytest

from braindance.importer.pipeline import errata_report, resolve_pool
from braindance.importer.schema import StreetCredCondition, StreetCredKind
from braindance.importer.sources import FetchResult


def record(**overrides):
    base = {
        "id": "wtnc-001",
        "base_card_id": "minotaur",
        "name": "Minotaur",
        "card_type": "unit",
        "color": "red",
        "eddie_cost": 5,
        "ram_cost": 2,
        "ram_provided": None,
        "power": 6,
        "has_sell_tag": True,
        "classification": ["Animals"],
        "keywords": None,
        "ability_text": "{Play} Defeat a rival Unit with power 5 or less.",
        "set_name": "Welcome to Night City — Retail",
        "set_code": "WTNC",
        "card_number": "001",
        "rarity": "rare",
        "is_current": True,
        "is_default_printing": True,
    }
    base.update(overrides)
    return base


def fetched(*records):
    return FetchResult(
        records=list(records),
        source="test",
        fetched_at="2026-09-10T00:00:00Z",
        from_cache=True,
    )


class TestRetailFilter:
    def test_keeps_retail_printing(self):
        pool = resolve_pool(fetched(record()))
        assert len(pool) == 1
        assert pool.cards[0].name == "Minotaur"

    def test_drops_card_with_no_retail_printing(self):
        # Promos and demo-deck exclusives are not the competitive pool.
        pool = resolve_pool(
            fetched(record(base_card_id="lucyna-kushinada", set_name="Promo Set"))
        )
        assert len(pool) == 0
        assert pool.stats.dropped_no_retail_printing == ["lucyna-kushinada"]

    def test_drop_is_reported_not_silent(self):
        pool = resolve_pool(
            fetched(
                record(),
                record(base_card_id="armored-minotaur", set_name="Alpha Kit Set"),
            )
        )
        assert len(pool) == 1
        assert "armored-minotaur" in pool.stats.dropped_no_retail_printing

    def test_starter_deck_and_box_toppers_count_as_retail(self):
        pool = resolve_pool(
            fetched(
                record(base_card_id="a", set_name="The Heist — Retail Starter Deck"),
                record(base_card_id="b", set_name="Box Toppers — Retail"),
            )
        )
        assert len(pool) == 2


class TestPrintingSelection:
    def test_prefers_current_printing(self):
        pool = resolve_pool(
            fetched(
                record(id="old", is_current=False, ability_text="{Play} Draw 1."),
                record(id="new", is_current=True, ability_text="{Play} Draw 2."),
            )
        )
        assert pool.cards[0].effect_text == "{Play} Draw 2."

    def test_collapses_duplicate_records(self):
        pool = resolve_pool(fetched(record(id="a"), record(id="b")))
        assert len(pool) == 1
        assert pool.stats.duplicate_records_collapsed == 1

    def test_selection_is_deterministic(self):
        # Repeat imports of unchanged data must produce identical pools, or every
        # downstream number becomes unreproducible.
        records = [
            record(id="z", is_current=True, is_default_printing=False),
            record(id="a", is_current=True, is_default_printing=False),
        ]
        first = resolve_pool(fetched(*records)).cards[0]
        second = resolve_pool(fetched(*reversed(records))).cards[0]
        assert first.card_number == second.card_number


class TestErrata:
    def test_flags_card_reworded_between_printings(self):
        pool = resolve_pool(
            fetched(
                record(set_name="Welcome to Night City — Beta",
                       ability_text="{Play} Defeat a rival Unit with power 4 or less."),
                record(ability_text="{Play} Defeat a rival Unit with power 5 or less."),
            )
        )
        assert pool.cards[0].has_errata is True
        assert pool.stats.cards_with_errata == ["Minotaur"]

    def test_identical_text_is_not_errata(self):
        pool = resolve_pool(
            fetched(record(set_name="Welcome to Night City — Beta"), record())
        )
        assert pool.cards[0].has_errata is False

    def test_brace_reformatting_is_not_errata(self):
        # Early printings wrote timing triggers as bare capitals. "PLAY" becoming
        # "{Play}" is a presentation change; flagging it as errata is noise.
        pool = resolve_pool(
            fetched(
                record(set_name="Main Set 01",
                       ability_text="PLAY Defeat all other Units."),
                record(ability_text="{Play} Defeat all other Units."),
            )
        )
        assert pool.cards[0].has_errata is False
        assert pool.stats.cards_reformatted_only == 1
        assert pool.stats.cards_with_errata == []

    def test_added_reminder_text_is_not_errata(self):
        # CR 3.18.1.2.2.1: reminder text does not influence gameplay.
        pool = resolve_pool(
            fetched(
                record(set_name="Welcome to Night City — Beta",
                       ability_text="{Blocker}"),
                record(ability_text="{Blocker} (You may spend this Unit to redirect.)"),
            )
        )
        assert pool.cards[0].has_errata is False
        assert pool.stats.cards_reformatted_only == 1

    def test_numeric_change_is_real_errata(self):
        pool = resolve_pool(
            fetched(
                record(set_name="Spoiler Set",
                       ability_text="Adjust a rival Gig by up to 2."),
                record(ability_text="Adjust a rival Gig by up to 1."),
            )
        )
        assert pool.cards[0].has_errata is True
        assert pool.stats.cards_reformatted_only == 0

    def test_reformatted_cards_excluded_from_diff_report(self):
        report = errata_report(
            fetched(
                record(set_name="Main Set 01", ability_text="PLAY Draw 1."),
                record(ability_text="{Play} Draw 1."),
            )
        )
        assert report == {}

    def test_errata_report_shows_both_texts(self):
        report = errata_report(
            fetched(
                record(set_name="Welcome to Night City — Beta",
                       ability_text="{Play} Draw 1."),
                record(ability_text="{Play} Draw 2."),
            )
        )
        assert "Minotaur" in report
        assert set(report["Minotaur"].values()) == {"{Play} Draw 1.", "{Play} Draw 2."}


class TestPoolAccessors:
    def test_legends_excluded_from_main_deck(self):
        # CR 7.3: the 40-50 card main deck contains no Legends.
        pool = resolve_pool(
            fetched(
                record(),
                record(
                    base_card_id="evelyn",
                    name="Evelyn Parker - Beautiful Enigma",
                    card_type="legend",
                    ram_cost=None,
                    ram_provided=2,
                    power=None,
                ),
            )
        )
        assert len(pool.legends) == 1
        assert len(pool.main_deck_cards) == 1
        assert pool.main_deck_cards[0].name == "Minotaur"

    def test_lookup_by_full_name(self):
        pool = resolve_pool(fetched(record()))
        assert pool.by_name("Minotaur") is not None
        assert pool.by_name("Nonexistent") is None

    def test_unparsed_street_cred_surfaces_in_stats(self):
        pool = resolve_pool(
            fetched(record(ability_text="If your ☆ is exactly 13, win the game."))
        )
        assert pool.stats.unparsed_street_cred_clauses


class TestSchemaGuards:
    def test_threshold_kind_requires_a_value(self):
        with pytest.raises(ValueError):
            StreetCredCondition(kind=StreetCredKind.ABSOLUTE_LESS_THAN, source="x")

    def test_comparison_kind_rejects_a_value(self):
        with pytest.raises(ValueError):
            StreetCredCondition(
                kind=StreetCredKind.RIVAL_MORE, value=5, source="x"
            )
