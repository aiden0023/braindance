"""Normalization tests.

Every card-text fixture here is verbatim from the live retail pool, so a regression
means the importer broke against real data rather than against an invented string.
"""

from __future__ import annotations

import pytest

from braindance.importer.normalize import (
    normalize_card,
    parse_street_cred,
    parse_triggers,
    split_name,
    strip_reminder_text,
)
from braindance.importer.schema import StreetCredKind, Trigger


class TestSplitName:
    def test_splits_legend_subtitle(self):
        assert split_name("Evelyn Parker - Beautiful Enigma") == (
            "Evelyn Parker",
            "Beautiful Enigma",
        )

    def test_plain_name_has_no_subtitle(self):
        assert split_name("MT0D12 Flathead") == ("MT0D12 Flathead", None)

    def test_splits_on_first_separator_only(self):
        # CR 7.3.1 bans two Legends sharing a *name*, so an over-eager split would
        # wrongly collide distinct cards.
        assert split_name("Royce - Don't Call Me - Simon") == (
            "Royce",
            "Don't Call Me - Simon",
        )

    def test_apostrophes_survive(self):
        assert split_name("Jackie Welles - Mama's Favorite") == (
            "Jackie Welles",
            "Mama's Favorite",
        )


class TestReminderText:
    def test_separates_reminder_from_effect(self):
        text = (
            "(Equip to a unit or face-up legend.) {Attack} If this unit wins a fight "
            "against a rival unit, draw a card."
        )
        effect, reminders = strip_reminder_text(text)
        assert reminders == ["Equip to a unit or face-up legend."]
        assert effect.startswith("{Attack}")
        assert "Equip to a unit" not in effect

    def test_effect_text_is_what_survives(self):
        # CR 3.18.1.2.2.1: reminder text does not influence gameplay, so interaction
        # search must not match against it.
        text = "{Blocker} (You may spend this Unit to redirect a rival Unit's attack to it instead.)"
        effect, reminders = strip_reminder_text(text)
        assert effect == "{Blocker}"
        assert len(reminders) == 1

    def test_text_without_parentheses_is_unchanged(self):
        text = "The first time a friendly ARASAKA Unit attacks each turn, draw 1."
        effect, reminders = strip_reminder_text(text)
        assert effect == text
        assert reminders == []


class TestTriggers:
    @pytest.mark.parametrize(
        "token,expected",
        [
            ("{Play}", Trigger.PLAY),
            ("{Attack}", Trigger.ATTACK),
            ("{Call}", Trigger.CALL),
            ("{Defeated}", Trigger.DEFEATED),
            ("{Spend}", Trigger.SPEND),
            ("{Blocker}", Trigger.BLOCKER),
            ("{Quick}", Trigger.QUICK),
            ("{Go Solo}", Trigger.GO_SOLO),
            ("{Adrenaline}", Trigger.ADRENALINE),
        ],
    )
    def test_every_known_trigger_parses(self, token, expected):
        triggers, unknown = parse_triggers(f"{token} Do a thing.")
        assert triggers == [expected]
        assert unknown == []

    def test_multiple_triggers_keep_order(self):
        text = "{Play} {Attack} Adjust a Gig by up to 1."
        triggers, _ = parse_triggers(text)
        assert triggers == [Trigger.PLAY, Trigger.ATTACK]

    def test_repeated_trigger_is_recorded_once(self):
        triggers, _ = parse_triggers("{Play} draw 1. {Play} draw 2.")
        assert triggers == [Trigger.PLAY]

    def test_unknown_token_is_reported_not_swallowed(self):
        # A new set's keyword must surface loudly rather than vanish.
        triggers, unknown = parse_triggers("{Netrun} Do something new.")
        assert triggers == []
        assert unknown == ["Netrun"]


class TestStreetCred:
    def test_absolute_threshold(self):
        text = "Then, if you have less than 20 ☆ (Street Cred), discard 1."
        conditions, unparsed = parse_street_cred(text)
        assert unparsed == []
        assert conditions[0].kind is StreetCredKind.ABSOLUTE_LESS_THAN
        assert conditions[0].value == 20

    def test_rival_comparison_more(self):
        text = "If you have more ☆ (Street Cred) than a Rival, defeat a rival Unit."
        conditions, unparsed = parse_street_cred(text)
        assert unparsed == []
        assert conditions[0].kind is StreetCredKind.RIVAL_MORE
        assert conditions[0].value is None

    def test_rival_comparison_less(self):
        text = "If you have less ☆ (Street Cred) than a Rival, this Unit can't be blocked."
        conditions, _ = parse_street_cred(text)
        assert conditions[0].kind is StreetCredKind.RIVAL_LESS

    def test_differs_by_threshold(self):
        text = "{Defeated} If your ☆ (Street Cred) differs from a Rival's by 10+, draw 2."
        conditions, unparsed = parse_street_cred(text)
        assert unparsed == []
        assert conditions[0].kind is StreetCredKind.RIVAL_DIFFERS_BY
        assert conditions[0].value == 10

    def test_parity(self):
        # Street Cred is a sum of die faces, so parity is a fair coin -- unless an
        # effect adjusts a Gig by an odd amount. This is why parity is modeled at all.
        text = "{Play} If your ☆ (Street Cred) is an even number, draw 1."
        conditions, unparsed = parse_street_cred(text)
        assert unparsed == []
        assert conditions[0].kind is StreetCredKind.PARITY_EVEN
        assert conditions[0].value is None

    def test_filled_star_variant_is_normalized(self):
        # Upstream uses U+2606 nearly everywhere but U+2605 on at least one card.
        text = "If you have more ★ (Street Cred) than a Rival, draw 1."
        conditions, unparsed = parse_street_cred(text)
        assert unparsed == []
        assert conditions[0].kind is StreetCredKind.RIVAL_MORE

    def test_unrecognised_condition_is_reported(self):
        text = "If your ☆ (Street Cred) is exactly 13, win the game."
        conditions, unparsed = parse_street_cred(text)
        assert conditions == []
        assert len(unparsed) == 1
        assert "exactly 13" in unparsed[0]

    def test_text_without_street_cred_yields_nothing(self):
        conditions, unparsed = parse_street_cred("{Play} Draw 1.")
        assert conditions == []
        assert unparsed == []


class TestNormalizeCard:
    @staticmethod
    def _raw(**overrides):
        raw = {
            "base_card_id": "satori-sword-of-saburo",
            "name": "Satori - Sword of Saburo",
            "card_type": "gear",
            "color": "red",
            "eddie_cost": 2,
            "ram_cost": 2,
            "ram_provided": None,
            "power": 1,
            "has_sell_tag": True,
            "classification": ["Weapon", "Arasaka"],
            "ability_text": (
                "(Equip to a unit or face-up legend.) {Attack} If this unit wins a "
                "fight against a rival unit, draw a card."
            ),
            "set_name": "Welcome to Night City — Retail",
            "set_code": "WTNC",
            "card_number": "020",
            "rarity": "rare",
        }
        raw.update(overrides)
        return raw

    def test_builds_card_with_parsed_structure(self):
        card, unknown, unparsed = normalize_card(self._raw())
        assert unknown == []
        assert unparsed == []
        assert card.name == "Satori"
        assert card.subtitle == "Sword of Saburo"
        assert card.full_name == "Satori - Sword of Saburo"
        assert card.triggers == [Trigger.ATTACK]
        assert card.has_sell_tag is True
        assert card.classification == ["Weapon", "Arasaka"]

    def test_raw_text_is_preserved_verbatim(self):
        raw = self._raw()
        card, _, _ = normalize_card(raw)
        assert card.raw_ability_text == raw["ability_text"]
        assert "Equip to a unit" not in card.effect_text
        assert card.reminder_text == ["Equip to a unit or face-up legend."]

    def test_card_with_no_text_is_fine(self):
        card, unknown, unparsed = normalize_card(self._raw(ability_text=None))
        assert card.effect_text == ""
        assert card.triggers == []
        assert (unknown, unparsed) == ([], [])
