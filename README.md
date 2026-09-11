# Braindance

A deck analysis engine for **Cyberpunk TCG**.

In 2077, a braindance lets you scrub a recorded experience layer by layer to find what
actually happened. Same idea here: hand it a decklist and it plays that deck thousands of
times to tell you what's going on underneath the vibes.

This is not a place to play games — that already exists. This is the layer that tells you
which deck to bring before you sit down. 17lands, not XMage.

## Status

Early. **M0 (importer + normalization) is in progress.** Nothing here is stable yet.

## Why it exists

*Welcome to Night City* launches 6 November 2026 with no established meta. Some things
about the format are computable rather than guessable, and nobody is computing them:

- **Economy consistency.** Eddies are a permanent, cumulative resource — each sold card
  stays in the Eddies area and readies every turn, like a land. You may take the Sell
  action only once per turn, and only 52% of the retail pool carries a Sell Tag. So
  "how often does this deck miss an Eddie drop by turn N?" is a hypergeometric question
  that decides games.
- **Legal deck space.** Your 3 Legends set a per-color RAM Limit, and a card is legal only
  if its RAM is within the limit for its color (CR 3.20.5.2). The legal pool is a
  computable function of your Legend trio.
- **Interaction search.** 150 cards with a nine-token trigger vocabulary is small enough
  to search exhaustively for two- and three-card interactions.

## Install

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows;  source .venv/bin/activate elsewhere
pip install -e ".[dev]"
```

## Use

```bash
braindance import                 # fetch, normalize, report
braindance import --refresh       # bypass the local cache
braindance import --diff          # cards whose rules text changed between printings
braindance pool --street-cred     # pool summary + Street Cred conditions
braindance show "Evelyn Parker"   # what the engine actually sees for a card
```

## Card data

**No card data is committed to this repository.** The importer fetches it at runtime into
`data/`, which is gitignored. Card names, rules text, art and symbols belong to
CD PROJEKT RED, WeirdCo and their licensors.

The pool is pinned to **retail printings**. 49 cards were reworded between the Alpha,
Beta and Retail printings, so deduplicating by name alone silently mixes errata into the
pool; `--diff` shows exactly what changed. Promo and demo-deck exclusives are excluded and
reported rather than dropped silently.

Upstream data comes from [Ripperdeck](https://ripperdeck.gg), an unaffiliated community
project with no published API terms. Cache aggressively and don't hammer it.

Rules references cite the official Comprehensive Rules (last updated 1 September 2026).
Place your own copies in `docs/rules/` — also gitignored.

## Disclaimer

This is an unofficial fan project. It is not affiliated with, endorsed, sponsored or
specifically approved by CD PROJEKT RED or WeirdCo. Cyberpunk, Cyberpunk 2077, and all
associated names, marks, card text and artwork are the property of their respective
owners. No ownership is claimed. This project displays no card art and redistributes no
card data. If a rights holder objects to anything here, contact me and I'll take it down
promptly.

## Licence

MIT — see [LICENSE](LICENSE). Applies to the engine code only, not to any game data it
fetches.
