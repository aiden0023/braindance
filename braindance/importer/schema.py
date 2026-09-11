"""Typed model of a Cyberpunk TCG card, normalized from upstream sources.

Deliberately *not* a mirror of any upstream schema. Upstream gives us display data;
this gives us the fields the rules actually operate on. Where the two disagree, the
Comprehensive Rules (docs/rules/comprehensive-rules.pdf) win.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Color(str, Enum):
    RED = "red"
    BLUE = "blue"
    GREEN = "green"
    YELLOW = "yellow"


class CardType(str, Enum):
    LEGEND = "legend"
    UNIT = "unit"
    PROGRAM = "program"
    GEAR = "gear"


class Trigger(str, Enum):
    """The complete brace-delimited trigger/keyword vocabulary.

    Nine tokens across the whole retail pool. Timing triggers (CR 3.18) say *when*;
    keywords say *what*. We keep them in one enum because the card text delimits them
    identically -- the distinction lives in `TIMING_TRIGGERS` below.
    """

    PLAY = "Play"
    ATTACK = "Attack"
    CALL = "Call"
    DEFEATED = "Defeated"
    SPEND = "Spend"
    BLOCKER = "Blocker"
    QUICK = "Quick"
    GO_SOLO = "Go Solo"
    ADRENALINE = "Adrenaline"


#: Triggers that specify *when* an effect happens (CR 3.18.1.2.1).
TIMING_TRIGGERS = frozenset(
    {Trigger.PLAY, Trigger.ATTACK, Trigger.CALL, Trigger.DEFEATED}
)

#: Triggers that are standing keywords rather than timing windows.
KEYWORDS = frozenset(
    {Trigger.SPEND, Trigger.BLOCKER, Trigger.QUICK, Trigger.GO_SOLO, Trigger.ADRENALINE}
)


class StreetCredKind(str, Enum):
    """Shapes of Street Cred condition observed in card text.

    Street Cred is the sum of the face values of your Gig dice (CR glossary), so these
    are predicates over a stochastic quantity -- not a static cost. Upstream models this
    as a single nullable integer, which cannot express any of these.
    """

    RIVAL_MORE = "rival_more"  # "more ☆ than a Rival"
    RIVAL_LESS = "rival_less"  # "less ☆ than a Rival"
    RIVAL_DIFFERS_BY = "rival_differs_by"  # "differs from a Rival's by 10+"
    ABSOLUTE_LESS_THAN = "absolute_less_than"  # "less than 20 ☆"
    PARITY_EVEN = "parity_even"  # "is an even number"


class StreetCredCondition(BaseModel):
    """A single Street Cred predicate parsed out of card text."""

    kind: StreetCredKind
    value: int | None = None
    #: The clause this was parsed from, kept verbatim for auditing.
    source: str

    @model_validator(mode="after")
    def _value_matches_kind(self) -> StreetCredCondition:
        needs_value = {
            StreetCredKind.RIVAL_DIFFERS_BY,
            StreetCredKind.ABSOLUTE_LESS_THAN,
        }
        if self.kind in needs_value and self.value is None:
            raise ValueError(f"{self.kind} requires a value")
        if self.kind not in needs_value and self.value is not None:
            raise ValueError(f"{self.kind} must not carry a value")
        return self


class Card(BaseModel):
    """One card, resolved to a single authoritative printing."""

    # Identity -------------------------------------------------------------
    base_card_id: str
    #: Name *without* subtitle. CR 7.3.1 forbids two Legends sharing a name, so the
    #: split matters for deck legality and is not cosmetic.
    name: str
    #: Text after the first " - ", if any. CR 7.3.3 keys the 3-copy limit on the
    #: name+subtitle pair.
    subtitle: str | None = None
    card_type: CardType
    color: Color

    # Rules-relevant numbers -----------------------------------------------
    #: Cost in Eddies. None where the card has a null cost (CR 4.5.3: such Legends
    #: cannot be played to the field at all).
    eddie_cost: int | None = None
    #: RAM required to legally include this card (CR 3.20.5.2). None for Legends.
    ram_cost: int | None = None
    #: RAM this card contributes to the deck's limits. Legends only (CR 3.20.5).
    ram_provided: int | None = None
    power: int | None = None
    #: Whether this card may be sold via the once-per-turn Main Phase action
    #: (CR 5.8.3). Effects may move non-tagged cards to the Eddies area (CR 11.9.2.1).
    has_sell_tag: bool = False

    # Text -----------------------------------------------------------------
    #: Verbatim upstream text. Never mutated; the audit trail.
    raw_ability_text: str = ""
    #: Rules text with reminder text removed (CR 3.18.1.2.2.1: reminder text does not
    #: influence gameplay). This is what interaction search should match against.
    effect_text: str = ""
    #: Parenthetical clauses stripped from `effect_text`, kept for display.
    reminder_text: list[str] = Field(default_factory=list)

    # Parsed structure -----------------------------------------------------
    triggers: list[Trigger] = Field(default_factory=list)
    street_cred: list[StreetCredCondition] = Field(default_factory=list)
    classification: list[str] = Field(default_factory=list)

    # Provenance -----------------------------------------------------------
    set_name: str = ""
    set_code: str = ""
    card_number: str = ""
    rarity: str | None = None
    #: True when other printings of this card carry different rules text.
    has_errata: bool = False

    @property
    def full_name(self) -> str:
        """Name as printed, used for the CR 7.3.3 copy limit."""
        return f"{self.name} - {self.subtitle}" if self.subtitle else self.name

    @property
    def is_legend(self) -> bool:
        return self.card_type is CardType.LEGEND

    @property
    def timing_triggers(self) -> list[Trigger]:
        return [t for t in self.triggers if t in TIMING_TRIGGERS]

    @property
    def keywords(self) -> list[Trigger]:
        return [t for t in self.triggers if t in KEYWORDS]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Card {self.full_name} ({self.color.value} {self.card_type.value})>"


class PoolStats(BaseModel):
    """What the importer did, so a run is auditable rather than trusted."""

    total_upstream_records: int
    resolved_cards: int
    dropped_no_retail_printing: list[str] = Field(default_factory=list)
    duplicate_records_collapsed: int = 0
    #: Cards whose *rules* changed between printings.
    cards_with_errata: list[str] = Field(default_factory=list)
    #: Cards whose text changed only in presentation (e.g. "PLAY" -> "{Play}", reminder
    #: text added). Not errata; counted so the distinction stays visible.
    cards_reformatted_only: int = 0
    unparsed_street_cred_clauses: list[str] = Field(default_factory=list)
    unknown_brace_tokens: list[str] = Field(default_factory=list)


class CardPool(BaseModel):
    """A resolved, validated set of cards plus the provenance of the run."""

    cards: list[Card]
    stats: PoolStats
    source: str
    fetched_at: str

    def __len__(self) -> int:
        return len(self.cards)

    def by_name(self, full_name: str) -> Card | None:
        return next((c for c in self.cards if c.full_name == full_name), None)

    @property
    def legends(self) -> list[Card]:
        return [c for c in self.cards if c.is_legend]

    @property
    def main_deck_cards(self) -> list[Card]:
        """Everything legal in a main deck -- i.e. every non-Legend (CR 7.3)."""
        return [c for c in self.cards if not c.is_legend]
