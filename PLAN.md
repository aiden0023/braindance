# Braindance — Plan

A deck analysis engine for Cyberpunk TCG. Not a place to play games; the layer that
tells you which deck to bring before you sit down.

**Decisions locked:** Python · goldfish simulator first · constructed only.

---

## 1. What the research actually found

Verified directly against live endpoints and the official rules PDF on 2026-09-10.

### The data layer

| Source | Status |
|---|---|
| `netdeck.gg/api/*` | **No API.** Client-rendered SPA; every path returns the HTML shell. |
| `ripperdeck.gg/api/cards` | **Live, unauthenticated JSON.** 1.3 MB, 520 records. Mechanically modeled. |
| `tcgcyberpunk.com/api/cards` | Live JSON but ~37 KB, appears paginated. Fallback / cross-check only. |
| `cyberpunktcg.com/docs/printable-gameplay-guide.pdf` | Real, 14 pages. Full ruleset. |

Ripperdeck's schema models *rules*, not card faces — `ram_cost`, `ram_provided`,
`has_sell_tag`, `street_cred_requirement`, `eddie_cost`, `power`, `keywords[]`,
`classification[]`, `ability_text`. This is the data layer. Build the importer against it,
cross-check against tcgcyberpunk.

### The pool is small and the effect vocabulary is tiny

Retail (launch-legal) pool after deduping printings: **150 unique cards** —
73 units, 34 programs, 26 legends, 17 gear. Evenly split across red/blue/green/yellow.

Every effect trigger is **brace-delimited in the rules text**, and there are only nine:

```
{Play} 27   {Spend} 17   {Blocker} 16   {Attack} 13   {Quick} 12
{Go Solo} 11   {Call} 7   {Defeated} 7   {Adrenaline} 4
```

A 150-card pool with a nine-token machine-delimited trigger vocabulary is a far smaller
rules engine than a general TCG. This is the single most important finding for scoping.

### Data hazards the importer must handle

1. **Printing errata — 41 cards were genuinely reworded across printings**
   (Alpha → Beta → Retail). A further 8 changed only in presentation (`PLAY` → `{Play}`,
   reminder text added), which is *not* errata and must not be reported as such.
   Comparing raw strings gives 49 and overstates the problem; comparing semantic content
   gives the real 41. Deduping by name alone silently mixes rules versions.
2. **`street_cred_requirement` is the wrong shape, not merely unpopulated.** It is a
   nullable integer, null on 100% of records — but Street Cred conditions are *predicates*:
   absolute thresholds, comparisons against the Rival, a magnitude-of-difference check,
   and **parity** (3 cards care whether your Street Cred is even). No integer field can
   represent these. Must be parsed into structured conditions.
3. **`keywords` is null on 74% of records.** Recoverable from the `{Brace}` tokens.
4. ~~Encoding damage~~ — **wrong, corrected.** The upstream payload is clean UTF-8 with
   zero U+FFFD. The `�` I saw was my Windows console (cp1252) failing to render U+2014.
   The one real inconsistency is two star glyphs: ☆ (U+2606) ×41 and ★ (U+2605) ×1.

So: not a passthrough client. A normalization layer that reparses `ability_text` into
structured triggers is the actual first deliverable.

---

## 2. The rules facts that drive the simulator

Verified against the **Comprehensive Rules (52 pp., last updated Sep 1 2026)**, now at
`docs/rules/comprehensive-rules.pdf`. Rule numbers cited. These reshape what "goldfish"
even means here.

**Deck construction is fully pinned (7.3):** 3 Legends + a main deck of 40–50 non-Legend
cards; max 3 copies of an identical name+subtitle combination (7.3.3); **no two Legends
may share a name** (7.3.1 — "V: Corporate Exile" and "V: Streetkid" are both "V" and
cannot coexist). That last one constrains Legend-trio enumeration and is easy to miss.

**RAM is confirmed a per-card filter (3.20.5.2):** *"Your deck may include any card with
RAM less than or equal to your deck's RAM Limit for its color."* RAM Limit per color =
sum of your Legends' RAM in that color (3.20.5.1), locked at deck composition and
unaffected if a Legend is removed during play (3.20.6). RAM has **no** effect on whether
you can play a card — deck legality only (3.20.6.1).

**Eddies are permanent and cumulative, not a per-turn pool.** Each face-down card in the
Eddies area is 1 Eddie. They spend (turn sideways) to pay costs and *ready at the start of
your turn*. Economy is a growing mana base, like lands — not a refreshing pool.

**You may sell only once per turn, and only cards with a sell tag.**
**Only 52 of the 124 main-deck cards (42%) carry a Sell Tag.** A turn where your hand
holds no sell-taggable card is a missed Eddie drop, and you are permanently behind curve.

*(Corrected from an earlier "78 of 150, 52%" — that counted Legends. Legends are never in
your hand or deck (CR 4.4), so their Sell Tags can never be used for the Main Phase Sell
action. The correct denominator is main-deck cards, and the real figure is worse: 42%.)*

> This is the core consistency metric and the reason the goldfish sim is worth building.
> It is precisely the "missed land drop" problem, it is hypergeometric, and nobody is
> publishing numbers on it.

**But ramp exists, and it's the key strategic axis (5.8.4):** *"During your turn you may
Sell as many cards you want through card effects, but may only take the main phase Sell
action once per turn."* And 11.9.2.1: a card moved into the Eddies area **by an effect
doesn't need a Sell Tag at all**. So sell-enabler density is a second economy dimension
sitting on top of sell-tag density — decks can break the one-per-turn curve. Any
consistency model that only counts sell tags will systematically misprice these decks.

**Cost reduction has a floor of 1 (11.8.3).** Effects that reduce what you pay can never
take it below 1 €$, and reduction doesn't alter the card's printed cost value (11.8.2).
No zero-cost loops via reduction — a real constraint on combo search.

**Legends are economy too.** 3 Legends, each spendable as 1 €$ whether face-up or
face-down, readying each turn. So effective Eddies ≈ (cards sold) + (unspent Legends).
Spending a Legend as currency competes with using its effect or `{Go Solo}`.

**First-player penalty:** the player going first spends their 2 leftmost Legends and
does not ready them on turn 1.

**Mulligan is free (7.9.2–7.9.3).** Draw 6; mulligan once by shuffling the full hand back
and drawing 6 again, with no card penalty. Optimal mulligan policy is therefore *exactly
computable* — pick the keep/mull threshold that maximizes P(on-curve), no cost term
needed. The player going first must declare and complete their mulligan before the second
player declares (7.9.2), which is irrelevant to goldfish but matters for M4.

**You cannot win without attacking.** Each player owns 6 Gig dice (d4, d6, d8, d10, d12,
d20), gaining one per turn. Winning requires starting a turn with **7** (1.10). You can
only ever reach 6 on your own, so at least one Gig must be stolen.

*Correcting the earlier read of overtime:* it does **not** simply start after turn 7.
Per 1.11.1, overtime begins after **two consecutive turns in which both players begin with
an empty fixer area** — usually but not necessarily after 7 turns each. In overtime, 7+
Gigs wins the instant you have them, not just at start of turn (1.11).

**Street Cred is stochastic and partly under your control.** Street Cred = sum of the
face values of your Gig dice. You choose which die to roll each turn, except the d20
which is always last. Die *ordering* is a real optimization — it shapes the Street Cred
curve that gates 13 cards' effects, trading expected value against variance.

**Deckbuilding is a filter, not an integer program.** Every Legend provides exactly
`ram_provided: 2`. Three Legends give 6 RAM split by color: mono (6), 2+1 (4/2), or
1+1+1 (2/2/2). A card is legal if its `ram_cost` ≤ your RAM in that card's color.
Observed `ram_cost` spread: 1→27 cards, 2→61, 3→21, 4→13, 5→1, 6→1. So ~88 cards are
always legal, 34 need two matching Legends, and 2 demand mono.

*(Correcting an earlier assumption: I had this as an ILP. It is a per-card filter keyed
on the Legend color split, which is simpler and fully enumerable — there are only a few
dozen distinct legal-pool shapes.)*

---

## 3. Architecture

```
braindance/
  importer/     fetch → normalize → validate → local cache (pinned to Retail)
    client.py       ripperdeck + tcgcyberpunk clients, ETag-aware
    normalize.py    encoding repair, {Brace} → triggers, ☆ → street_cred_requirement
    schema.py       pydantic models; fail loudly on unknown tokens
  rules/        card-agnostic game state
    state.py        zones, Eddies, Legends, Gig dice, Street Cred
    economy.py      sell / spend / ready / Legend-as-Eddie
    dice.py         fixer ordering, roll, Street Cred
  effects/      one module per trigger; one test per implemented card
  analysis/
    hypergeometric.py   closed-form draw math
    goldfish.py         Monte Carlo solitaire
    mulligan.py         exact policy solver (free mulligan ⇒ tractable)
    combo.py            exhaustive 2- and 3-card interaction search over 150 cards
    legality.py         legal-pool enumeration per Legend color split
  cli/
  tests/
  data/         gitignored — never commit card data
```

**Legal posture, unchanged and correct:** engine and importer in the repo, card data never
committed, users run the importer to pull data at runtime. README carries the standard
community-resource disclaimer (names/art/text belong to CD PROJEKT RED and WeirdCo,
no affiliation, prompt takedown on request). MIT or Apache-2.0 — permissive, because
card-effect implementation parallelizes perfectly and a test-per-card structure makes
drive-by PRs trivially reviewable.

---

## 4. Milestones

**M0 — Importer + normalization. ✅ DONE.** Fetches, pins to Retail, parses braces into
triggers, extracts Street Cred predicates from prose, separates reminder text from effect
text, classifies errata vs. reformatting, validates via pydantic. `--diff` surfaces the 41
real rewordings. Resolves 520 upstream records → **150 cards** with zero unknown brace
tokens and zero unparsed Street Cred clauses. 49 tests. *Deliverable: a trustworthy local
card pool.*

**M1 — Static analysis, no engine.** Legal-pool enumeration per Legend split; rate curves;
sell-tag density by color and archetype; exhaustive 2- and 3-card interaction search over
the brace-trigger graph. *Deliverable: publishable findings before a single game is
simulated.*

**M2 — Goldfish simulator.** Turn loop, Eddie accumulation, sell decisions, Legend-as-
currency tradeoff, Lag, die ordering. No opponent, no combat. Outputs: P(Eddie drop missed
by turn N), turn-to-payoff distributions, brick rate, curve-out probability.
*Deliverable: the number that justifies the project.*

**M3 — Mulligan solver.** Exact keep/mull policy per deck given the free mulligan.

**M4 — Effects coverage.** Implement the nine triggers card by card, test per card.
This is the parallelizable community-contribution surface.

Two-player combat is explicitly out of scope for now — revisit after M4.

---

## 5. Open questions and risks

**Resolved** (was blocking M1): RAM rule ✓ 3.20.5.2 · deck size 40–50 ✓ 7.3.2 ·
3-copy limit ✓ 7.3.3 · mulligan ✓ 7.9 · Eddie persistence ✓ 5.8. Comprehensive Rules
obtained and stored locally. **No tournament/competitive ruleset exists yet** — confirmed;
"side deck" appears exactly once (1.7.1, an aside) with no rules defining it, so there is
no sideboarding to model. Revisit when an organized-play document ships.

**Live contradiction in the official rules — affects the economy model.**
- **5.8.4:** "you may Sell as many cards you want through card effects, but may only take
  the main phase Sell action once per turn."
- **11.9.2.2:** "An effect that says 'Sell' does count as a player's 'Sell A Card' Main
  phase action."

These disagree on whether an effect-driven Sell consumes your once-per-turn action.
The gap matters a lot: under 5.8.4 sell-enabler decks scale freely; under 11.9.2.2 they're
capped. Model it as a **configurable flag** (`effect_sell_consumes_action: bool`), report
both numbers until clarified, and ask the developers in Discord. A plausible reading that
reconciles them: effects reading literally "Sell" consume the action, while effects that
*place a card into the Eddies area* (11.9.2.1, no Sell Tag required) do not — but that is
inference, not rules text.

**Remaining risks**
- **Ripperdeck is an unaffiliated third party with no published API terms.** No rate-limit
  or stability guarantee. Cache aggressively, set a descriptive User-Agent, and treat a
  schema change as an expected event. Worth asking them directly before depending on it.
- **No fan content policy from WeirdCo was found.** Absence of evidence only. Check before
  publishing publicly. Not legal advice.
- **Card text supersedes the rules (2.5)** and cards may explicitly break deckbuilding
  restrictions (7.3.5). The engine needs a per-card override hook from day one rather than
  a hardcoded rules core — cheap now, very expensive to retrofit.
