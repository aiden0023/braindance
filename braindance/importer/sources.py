"""Fetching and caching upstream card data.

Card data is never committed to this repository -- it belongs to CD PROJEKT RED and
WeirdCo. The importer pulls it at runtime into `data/`, which is gitignored.

Upstream is an unaffiliated third party with no published API terms or stability
guarantee. Treat every fetch as best-effort, cache aggressively, and identify ourselves
honestly so the operators can contact us if we are a nuisance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

USER_AGENT = (
    "braindance/0.1 (Cyberpunk TCG deck analysis; "
    "https://github.com/aidenfornalski/braindance)"
)

DEFAULT_CACHE_DIR = Path("data")
CACHE_FILENAME = "ripperdeck-cards.json"
METADATA_FILENAME = "ripperdeck-cards.meta.json"

RIPPERDECK_CARDS_URL = "https://ripperdeck.gg/api/cards"


@dataclass(frozen=True)
class FetchResult:
    records: list[dict]
    source: str
    fetched_at: str
    from_cache: bool


def _cache_paths(cache_dir: Path) -> tuple[Path, Path]:
    return cache_dir / CACHE_FILENAME, cache_dir / METADATA_FILENAME


def load_cached(cache_dir: Path = DEFAULT_CACHE_DIR) -> FetchResult | None:
    """Return the cached payload, or None if there isn't a usable one."""
    cards_path, meta_path = _cache_paths(cache_dir)
    if not cards_path.exists():
        return None
    records = json.loads(cards_path.read_text(encoding="utf-8"))
    meta = (
        json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    )
    return FetchResult(
        records=records,
        source=meta.get("source", RIPPERDECK_CARDS_URL),
        fetched_at=meta.get("fetched_at", "unknown"),
        from_cache=True,
    )


def fetch_cards(
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    refresh: bool = False,
    timeout: float = 30.0,
) -> FetchResult:
    """Fetch the card list, using the local cache unless `refresh` is set.

    Falls back to a stale cache if the network fails -- a slightly old pool is far more
    useful than no pool, and the caller can see `fetched_at` to judge.
    """
    if not refresh:
        cached = load_cached(cache_dir)
        if cached is not None:
            return cached

    try:
        response = httpx.get(
            RIPPERDECK_CARDS_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        records = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        cached = load_cached(cache_dir)
        if cached is None:
            raise RuntimeError(
                f"Could not fetch cards from {RIPPERDECK_CARDS_URL} and no cache "
                f"exists in {cache_dir}/. Original error: {exc}"
            ) from exc
        return cached

    if not isinstance(records, list) or not records:
        raise RuntimeError(
            f"{RIPPERDECK_CARDS_URL} returned {type(records).__name__}, expected a "
            "non-empty list. The upstream schema may have changed."
        )

    fetched_at = datetime.now(UTC).isoformat()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cards_path, meta_path = _cache_paths(cache_dir)
    cards_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    meta_path.write_text(
        json.dumps(
            {
                "source": RIPPERDECK_CARDS_URL,
                "fetched_at": fetched_at,
                "record_count": len(records),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return FetchResult(
        records=records,
        source=RIPPERDECK_CARDS_URL,
        fetched_at=fetched_at,
        from_cache=False,
    )
