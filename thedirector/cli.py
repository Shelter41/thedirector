import asyncio
import logging

import click

from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@click.group()
def cli():
    """The Director — LLM Wiki knowledge base from email and Slack."""
    pass


@cli.command()
@click.option("--data-root", default=None, help="Data root directory")
def init(data_root: str | None):
    """Initialize the data directory structure."""
    from pathlib import Path
    from .store.wiki import init_knowledgebase

    root = data_root or settings.data_root
    Path(root).mkdir(parents=True, exist_ok=True)
    (Path(root) / "raw").mkdir(exist_ok=True)
    init_knowledgebase(root)
    click.echo(f"Initialized at {root}")
    click.echo(f"  raw/          — ingested messages")
    click.echo(f"  knowledgebase/ — LLM-generated wiki")


@cli.command(name="migrate-creds")
def migrate_creds():
    """One-shot: copy OAuth credentials out of Postgres into data/credentials.json.

    Run this once before tearing down Postgres. Reads using the same
    DATABASE_URL the rest of the app used to use. Skips short-lived
    *_oauth_state rows since those have no value across the migration.
    """
    asyncio.run(_migrate_creds())


async def _migrate_creds():
    """Connect to a (legacy) Postgres `credentials` table and copy each row
    into the new file-backed store. psycopg is imported lazily so a fresh
    install without it can still ship the rest of the CLI.
    """
    import json as _json
    import os

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        click.echo(
            "psycopg is not installed. Install it temporarily to run the migration:",
            err=True,
        )
        click.echo("  pip install 'psycopg[binary]>=3.2.0'", err=True)
        raise SystemExit(1)

    from .store import credentials as creds_store

    data_root = settings.data_root

    # The legacy DATABASE_URL is no longer in our settings — read it from the
    # raw env or fall back to the historical default.
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://thedirector:thedirector_dev@localhost:5433/thedirector",
    )
    click.echo(f"Reading from {db_url}")

    try:
        async with await psycopg.AsyncConnection.connect(db_url, row_factory=dict_row) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT provider, data, updated_at FROM credentials ORDER BY provider"
                )
                rows = await cur.fetchall()
    except Exception as e:
        click.echo(f"Failed to connect to or read from Postgres: {e}", err=True)
        click.echo("Is your Postgres container running? `docker compose up -d`", err=True)
        raise SystemExit(1)

    migrated: list[str] = []
    skipped: list[str] = []

    for row in rows:
        provider = row["provider"]
        if provider.endswith("_oauth_state"):
            skipped.append(provider)
            continue

        data = row["data"]
        if isinstance(data, str):
            data = _json.loads(data)

        try:
            creds_store.set(data_root, provider, data)
            migrated.append(provider)
        except Exception as e:
            click.echo(f"  ! failed to write {provider}: {e}", err=True)

    if migrated:
        click.echo(f"Migrated {len(migrated)} provider(s): {', '.join(migrated)}")
        click.echo(f"Wrote: {creds_store.credentials_path(data_root)}")
        click.echo("File mode: 0600 (owner read/write only)")
    else:
        click.echo("No credentials found to migrate.")

    if skipped:
        click.echo(f"Skipped {len(skipped)} short-lived OAuth state row(s): {', '.join(skipped)}")

    click.echo("\nNext steps:")
    click.echo("  1. Inspect the file:  cat data/credentials.json | jq")
    click.echo("  2. Pull the code commit that switches the call sites to the file store")
    click.echo("  3. Tear down Postgres:  docker compose down -v")


@cli.command()
@click.option("--source", type=click.Choice(["gmail", "slack", "notion", "all"]), default="all")
@click.option("--days", default=30, help="Number of days to fetch")
def ingest(source: str, days: int):
    """Fetch messages and run the wiki loop."""
    asyncio.run(_ingest(source, days))


async def _ingest(source: str, days: int):
    from datetime import datetime, timezone
    from .connectors.gmail import GmailConnector
    from .connectors.slack import SlackConnector
    from .connectors.notion import NotionConnector
    from .store import raw as raw_store
    from .wiki import loop as wiki_loop

    MUTABLE_SOURCES = {"notion"}

    data_root = settings.data_root

    try:
        messages = []

        async def cli_progress(event, data):
            if event == "fetching":
                if "fetched" in data:
                    subj = data.get("last_subject", "")
                    click.echo(f"  [{data['source']}] {data['fetched']} fetched — {subj}")
                elif data.get("phase") == "channel":
                    click.echo(f"  [slack] channel {data['channel_index']}/{data['channel_total']}: {data['channel']}")

        if source in ("gmail", "all"):
            gmail = GmailConnector()
            if await gmail.is_connected():
                click.echo("Fetching Gmail...")
                last_sync = raw_store.get_sync_cursor(data_root, "gmail")
                skip_ids = raw_store.existing_ids(data_root, "gmail")
                fetch_started = datetime.now(timezone.utc)
                msgs = await gmail.fetch(
                    since_days=days,
                    last_sync=last_sync,
                    skip_ids=skip_ids,
                    on_progress=cli_progress,
                )
                raw_store.set_sync_cursor(data_root, "gmail", fetch_started)
                click.echo(f"  Got {len(msgs)} messages")
                messages.extend(msgs)
            else:
                click.echo("Gmail not connected, skipping")

        if source in ("slack", "all"):
            slack = SlackConnector()
            if await slack.is_connected():
                click.echo("Fetching Slack...")
                last_sync = raw_store.get_sync_cursor(data_root, "slack")
                fetch_started = datetime.now(timezone.utc)
                msgs = await slack.fetch(
                    since_days=days,
                    last_sync=last_sync,
                    on_progress=cli_progress,
                )
                raw_store.set_sync_cursor(data_root, "slack", fetch_started)
                click.echo(f"  Got {len(msgs)} messages")
                messages.extend(msgs)
            else:
                click.echo("Slack not connected, skipping")

        if source in ("notion", "all"):
            notion = NotionConnector()
            if await notion.is_connected():
                click.echo("Fetching Notion...")
                last_sync = raw_store.get_sync_cursor(data_root, "notion")
                fetch_started = datetime.now(timezone.utc)
                msgs = await notion.fetch(
                    since_days=days,
                    last_sync=last_sync,
                    on_progress=cli_progress,
                )
                raw_store.set_sync_cursor(data_root, "notion", fetch_started)
                click.echo(f"  Got {len(msgs)} pages")
                messages.extend(msgs)
            else:
                click.echo("Notion not connected, skipping")

        if not messages:
            click.echo("No messages to process")
            return

        # Write to raw
        new_count = 0
        for msg in messages:
            overwrite = msg.source in MUTABLE_SOURCES
            if raw_store.write(data_root, msg, overwrite=overwrite):
                new_count += 1

        click.echo(f"Stored {new_count} new messages ({len(messages)} total fetched)")

        if new_count == 0:
            click.echo("Nothing new to process")
            return

        # Wiki loop
        click.echo("Running wiki loop...")

        async def on_progress(event, data):
            if event == "page_update":
                click.echo(f"  {data['action']}: {data['page']} — {data['reason']}")
            elif event == "complete":
                click.echo(f"  Done: {data['created']} created, {data['updated']} updated")

        await wiki_loop.run(data_root, on_progress=on_progress)
    except Exception as e:
        click.echo(f"Ingest failed: {e}", err=True)
        raise


@cli.command()
@click.argument("question")
def query(question: str):
    """Ask a question about the knowledge base."""
    asyncio.run(_query(question))


async def _query(question: str):
    from .wiki.query import query as wiki_query

    result = await wiki_query(settings.data_root, question)
    click.echo(result["answer"])
    if result["sources"]:
        click.echo(f"\nSources: {', '.join(result['sources'])}")


@cli.command()
def lint():
    """Check the wiki for quality issues."""
    from .wiki.lint import lint as wiki_lint

    report = wiki_lint(settings.data_root)
    click.echo(f"Pages: {report['total_pages']}")

    if report["broken_refs"]:
        click.echo(f"\nBroken references ({len(report['broken_refs'])}):")
        for br in report["broken_refs"]:
            click.echo(f"  {br['page']} → [[{br['ref']}]]")

    if report["orphan_pages"]:
        click.echo(f"\nOrphan pages ({len(report['orphan_pages'])}):")
        for op in report["orphan_pages"]:
            click.echo(f"  {op}")

    if report["stale_pages"]:
        click.echo(f"\nStale pages ({len(report['stale_pages'])}):")
        for sp in report["stale_pages"]:
            click.echo(f"  {sp['page']} (last updated: {sp['last_updated']})")

    if report["issues"]:
        click.echo(f"\nOther issues ({len(report['issues'])}):")
        for issue in report["issues"]:
            click.echo(f"  {issue['page']}: {issue['issue']}")

    if report["healthy"]:
        click.echo("\nWiki is healthy!")


@cli.command()
def status():
    """Show current status."""
    from .store import raw as raw_store
    from .store import wiki as wiki_store

    data_root = settings.data_root
    pages = wiki_store.page_count(data_root)
    raw_count = raw_store.count(data_root)
    cursor = raw_store.get_cursor(data_root)

    click.echo(f"Data root: {data_root}")
    click.echo(f"Raw messages: {raw_count}")
    click.echo(f"Wiki pages: {pages}")
    click.echo(f"Last processed: {cursor.isoformat() if cursor else 'never'}")

    # Page breakdown — discover whatever directories the LLM has chosen
    for d in wiki_store.list_directories(data_root):
        type_pages = wiki_store.list_pages(data_root, d)
        if type_pages:
            click.echo(f"  {d}: {len(type_pages)}")
