import json
import logging
import signal
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

from forge_astra.artifacts import write_atomic
from forge_astra.config import Settings
from forge_astra.models import Card
from forge_astra.service import Application
from forge_astra.storage import Store
from forge_astra.upstream import UPSTREAM_URL, git

app = typer.Typer(
    no_args_is_help=True, help="Research MTG spoilers and prepare Forge script drafts."
)


@app.callback()
def main(
    ctx: typer.Context,
    env_file: Annotated[
        Path, typer.Option(help="Environment file; process environment wins.")
    ] = Path(".env"),
):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ctx.obj = Settings(_env_file=env_file)


def prepare(application: Application, sync: bool):
    if sync:
        application.sync()
    else:
        path = application.snapshot.path
        if git(path, "remote", "get-url", "origin") != UPSTREAM_URL or git(
            path, "status", "--porcelain"
        ):
            raise ValueError("Cached snapshot is not clean upstream content")
        application.snapshot.commit = git(path, "rev-parse", "HEAD")
        application.corpus.index(path, application.snapshot.commit)


@app.command()
def sync(ctx: typer.Context):
    """Fetch upstream Forge and rebuild the script/document index."""
    application = Application(ctx.obj)
    try:
        with application.lock():
            typer.echo(application.sync())
    finally:
        application.close()


@app.command()
def scan(ctx: typer.Context, day: str = "", backfill: bool = False):
    """Discover spoilers without invoking a model. First scan seeds a baseline."""
    application = Application(ctx.obj)
    try:
        with application.lock():
            typer.echo(
                json.dumps(
                    application.discover(
                        date.fromisoformat(day) if day else application.today(), backfill
                    )
                )
            )
    finally:
        application.close()


@app.command()
def run(
    ctx: typer.Context,
    day: str = "",
    discover: bool = True,
    sync: bool = True,
    backfill: bool = False,
    drain: bool = False,
):
    """Run one poll and process the durable queue, exporting one group per set."""
    application = Application(ctx.obj)
    try:
        with application.lock():
            target = date.fromisoformat(day) if day else application.today()
            prepare(application, sync)
            if discover:
                application.discover(target, backfill)
            result = (
                {"batches": list(application.drain(target))}
                if drain
                else application.process(target)
            )
            typer.echo(json.dumps(result, indent=2))
    finally:
        application.close()


@app.command()
def watch(ctx: typer.Context):
    """Poll continuously; stop cleanly on SIGTERM/SIGINT. Suitable for a container."""
    settings: Settings = ctx.obj
    from forge_astra.worker import poll_once

    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    while not stopping.is_set():
        poll_once(settings, stopping)
        stopping.wait(settings.poll_seconds)


@app.command()
def health(ctx: typer.Context):
    """Exit nonzero when the last poll failed or the worker is stale."""
    settings: Settings = ctx.obj
    path = settings.data_dir / "health.json"
    if not path.exists():
        raise typer.Exit(1)
    record = json.loads(path.read_text())
    last_activity = record.get("last_activity", record["last_poll"])
    age = (datetime.now(UTC) - datetime.fromisoformat(last_activity)).total_seconds()
    typer.echo(json.dumps(record))
    if (
        record["status"] not in {"ok", "running"}
        or record.get("phase") == "stopped"
        or age > settings.poll_seconds * 2 + 600
    ):
        raise typer.Exit(1)


@app.command()
def status(ctx: typer.Context):
    """Show queue counts and tracked mechanic blockers."""
    store = Store(ctx.obj.db_path)
    try:
        counts = dict(store.db.execute("SELECT status,count(*) FROM cards GROUP BY status"))
        typer.echo(json.dumps({"cards": counts, "mechanics": store.mechanics()}, indent=2))
    finally:
        store.close()


@app.command("import-cards")
def import_cards(ctx: typer.Context, path: Path):
    """Queue a JSON list of Scryfall card objects (explicit backfill or harness input)."""
    application = Application(ctx.obj)
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            data = data.get("data", [data])
        cards = [Card.from_scryfall(item) for item in data]
        with application.lock():
            for card in cards:
                application.store.enqueue(card, application.today())
        typer.echo(f"Queued {len(cards)} cards")
    finally:
        application.close()


@app.command("cards")
def list_cards(
    ctx: typer.Context,
    status: Annotated[str, typer.Option("--status")] = "",
    set_code: Annotated[str, typer.Option("--set")] = "",
    name: str = "",
    limit: Annotated[int, typer.Option(min=1, max=500)] = 50,
    offset: Annotated[int, typer.Option(min=0)] = 0,
):
    """List card keys, statuses, blockers and latest artifact paths as JSON."""
    if status and status not in {
        "baseline",
        "pending",
        "error",
        "blocked",
        "needs_review",
        "draft",
        "already_upstream",
    }:
        raise typer.BadParameter("Unknown card status")
    store = Store(ctx.obj.db_path)
    try:
        typer.echo(
            json.dumps(
                store.list_cards(
                    status=status, set_code=set_code, name=name, limit=limit, offset=offset
                ),
                indent=2,
            )
        )
    finally:
        store.close()


@app.command("show")
def show_card(ctx: typer.Context, card_key: str):
    """Inspect a card's source metadata, discovery history and latest result."""
    store = Store(ctx.obj.db_path)
    try:
        card = store.get_card(card_key)
        if card is None:
            raise typer.BadParameter("Unknown card key")
        typer.echo(json.dumps(card, indent=2))
    finally:
        store.close()


@app.command()
def retry(ctx: typer.Context, card_key: str):
    """Queue a card again after feedback or a local review."""
    store = Store(ctx.obj.db_path)
    try:
        store.retry(card_key)
    finally:
        store.close()


@app.command("track-mechanic")
def track_mechanic(
    ctx: typer.Context, name: str, pattern: str = "", pr: int | None = typer.Option(None, min=1)
):
    """Require a specific upstream implementation PR for a named mechanic."""
    store = Store(ctx.obj.db_path)
    try:
        store.track_mechanic(name, pattern or name, "Explicit implementation dependency", pr)
        typer.echo(f"Tracking {name}" + (f" against PR #{pr}" if pr else ""))
    finally:
        store.close()


@app.command()
def feedback(
    ctx: typer.Context,
    card_key: str,
    note: str,
    outcome: str = "unverified",
    retry_card: bool = False,
):
    """Record human/harness findings as reviewed, unverified or rejected knowledge."""
    if outcome not in {"reviewed", "unverified", "rejected"}:
        raise typer.BadParameter("outcome must be reviewed, unverified, or rejected")
    store = Store(ctx.obj.db_path)
    try:
        if not store.db.execute("SELECT 1 FROM cards WHERE key=?", (card_key,)).fetchone():
            raise typer.BadParameter("Unknown card key")
        typer.echo(store.lesson(note, outcome, {"source": "explicit_feedback"}, card_key))
        if retry_card:
            store.retry(card_key)
    finally:
        store.close()


@app.command("export-knowledge")
def export_knowledge(ctx: typer.Context, output: Path):
    """Export the accumulated knowledge as readable Markdown."""
    store = Store(ctx.obj.db_path)
    try:
        text = store.knowledge("")["seed"] + "\n# Learned notes\n"
        for row in store.db.execute("SELECT * FROM lessons ORDER BY created_at"):
            text += f"\n## {row['id']} ({row['status']})\n\n{row['content']}\n\nProvenance: `{row['provenance']}`\n"
        write_atomic(output, text)
    finally:
        store.close()


@app.command("evaluate")
def evaluate_command(
    ctx: typer.Context, tier: int | None = None, case: str = "", sync: bool = True
):
    """Run renamed-card benchmarks against the configured real model endpoint."""
    from forge_astra.evaluation import evaluate

    application = Application(ctx.obj)
    try:
        with application.lock():
            prepare(application, sync)
            result = evaluate(application, tier=tier, case_id=case or None)
            typer.echo(json.dumps(result, indent=2))
            if result["passed"] != result["total"]:
                raise typer.Exit(1)
    finally:
        application.close()


if __name__ == "__main__":
    app()
