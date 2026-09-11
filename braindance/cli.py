"""Command line interface for Braindance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .importer import errata_report, fetch_cards, resolve_pool
from .importer.schema import CardType

app = typer.Typer(
    add_completion=False,
    help="Deck analysis for Cyberpunk TCG.",
    no_args_is_help=True,
)
console = Console()

CacheDir = Annotated[
    Path, typer.Option("--cache-dir", help="Where to read/write cached card data.")
]


@app.command("import")
def import_cards(
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Re-fetch even if a cache exists.")
    ] = False,
    diff: Annotated[
        bool,
        typer.Option("--diff", help="Show cards whose rules text changed between printings."),
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write the resolved pool to this JSON file."),
    ] = None,
    cache_dir: CacheDir = Path("data"),
) -> None:
    """Fetch the card pool, normalize it, and report what happened."""
    fetched = fetch_cards(cache_dir=cache_dir, refresh=refresh)
    origin = "cache" if fetched.from_cache else fetched.source
    console.print(
        f"[dim]{len(fetched.records)} records from {origin} "
        f"(fetched {fetched.fetched_at})[/dim]"
    )

    pool = resolve_pool(fetched)
    stats = pool.stats

    table = Table(title="Resolved pool", show_header=False, box=None)
    table.add_row("Cards", str(stats.resolved_cards))
    for card_type in CardType:
        count = sum(1 for c in pool.cards if c.card_type is card_type)
        table.add_row(f"  {card_type.value}s", str(count))
    table.add_row("Duplicate printings collapsed", str(stats.duplicate_records_collapsed))
    table.add_row("Cards with errata (rules changed)", str(len(stats.cards_with_errata)))
    table.add_row("Cards reformatted only", str(stats.cards_reformatted_only))
    table.add_row(
        "Dropped (no retail printing)", str(len(stats.dropped_no_retail_printing))
    )
    console.print(table)

    if stats.dropped_no_retail_printing:
        console.print(
            "\n[yellow]Dropped as non-retail (promo/demo/pre-release):[/yellow] "
            + ", ".join(stats.dropped_no_retail_printing)
        )

    # These two are the loud failures: they mean the parser met something new.
    if stats.unknown_brace_tokens:
        console.print(
            "\n[red]Unknown brace tokens (new keywords?):[/red] "
            + ", ".join(stats.unknown_brace_tokens)
        )
    if stats.unparsed_street_cred_clauses:
        console.print("\n[red]Unparsed Street Cred clauses:[/red]")
        for clause in stats.unparsed_street_cred_clauses:
            console.print(f"  • {clause}")

    if diff:
        _print_errata(fetched)

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            pool.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
        )
        console.print(f"\n[green]Wrote[/green] {out}")


def _print_errata(fetched) -> None:
    report = errata_report(fetched)
    console.print(f"\n[bold]Rules text differs across printings: {len(report)} cards[/bold]")
    for name, texts in report.items():
        console.print(f"\n[cyan]{name}[/cyan]")
        for set_name, text in texts.items():
            console.print(f"  [dim]{set_name}[/dim]")
            console.print(f"    {text or '(no text)'}")


@app.command()
def pool(
    cache_dir: CacheDir = Path("data"),
    street_cred: Annotated[
        bool, typer.Option("--street-cred", help="List cards with Street Cred conditions.")
    ] = False,
) -> None:
    """Summarize the resolved card pool."""
    fetched = fetch_cards(cache_dir=cache_dir)
    resolved = resolve_pool(fetched)

    sellable = sum(1 for c in resolved.main_deck_cards if c.has_sell_tag)
    main_deck = len(resolved.main_deck_cards)

    table = Table(title=f"Card pool ({len(resolved)} cards)")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Legends", str(len(resolved.legends)))
    table.add_row("Main-deck cards", str(main_deck))
    table.add_row(
        "  with a Sell Tag",
        f"{sellable} ({sellable / main_deck:.0%})" if main_deck else "0",
    )
    table.add_row("  with Street Cred conditions",
                  str(sum(1 for c in resolved.main_deck_cards if c.street_cred)))
    console.print(table)

    if street_cred:
        console.print("\n[bold]Street Cred conditions[/bold]")
        for card in resolved.cards:
            for condition in card.street_cred:
                value = f" ({condition.value})" if condition.value is not None else ""
                console.print(
                    f"  [cyan]{card.full_name:34}[/cyan] "
                    f"{condition.kind.value}{value}  [dim]{condition.source}[/dim]"
                )


@app.command()
def show(
    name: Annotated[str, typer.Argument(help="Card name (or part of one).")],
    cache_dir: CacheDir = Path("data"),
) -> None:
    """Show the normalized form of a card -- what the engine actually sees."""
    fetched = fetch_cards(cache_dir=cache_dir)
    resolved = resolve_pool(fetched)

    needle = name.casefold()
    matches = [c for c in resolved.cards if needle in c.full_name.casefold()]
    if not matches:
        console.print(f"[red]No card matching[/red] {name!r}")
        raise typer.Exit(1)

    for card in matches[:10]:
        console.print(f"\n[bold cyan]{card.full_name}[/bold cyan]")
        console.print(
            f"  {card.color.value} {card.card_type.value} · "
            f"cost {card.eddie_cost} · RAM {card.ram_cost} · power {card.power}"
            + (f" · provides {card.ram_provided} RAM" if card.ram_provided else "")
        )
        console.print(f"  sell tag: {card.has_sell_tag}   errata: {card.has_errata}")
        if card.triggers:
            console.print(f"  triggers: {', '.join(t.value for t in card.triggers)}")
        if card.street_cred:
            for condition in card.street_cred:
                console.print(f"  street cred: {condition.kind.value} {condition.value or ''}")
        if card.effect_text:
            console.print(f"  [white]{card.effect_text}[/white]")
        if card.reminder_text:
            for reminder in card.reminder_text:
                console.print(f"  [dim]({reminder})[/dim]")


if __name__ == "__main__":  # pragma: no cover
    app()
