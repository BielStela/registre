"""Time tracking app"""

from __future__ import annotations

import contextlib
import datetime
import itertools
import json
import os
import sqlite3
import sys
from collections.abc import Generator
from datetime import timezone
from pathlib import Path
from typing import Callable, NamedTuple

import click
import platformdirs
from rich import print
from rich.table import Table

from registre import __version__

APP_NAME = "registre"
APP_AUTHOR = "biel"

T_FORMAT = "%Y-%m-%d %H:%M:%S"


def _adapt_datetime_epoch(d: datetime.datetime) -> float:
    """Adapt datetime.datetime to Unix timestamp."""
    return float(d.timestamp())


def _convert_timestamp(x: bytes) -> datetime.datetime:
    """Convert Unix epoch timestamp to datetime.datetime object."""
    return datetime.datetime.fromtimestamp(float(x), tz=timezone.utc)


sqlite3.register_adapter(datetime.datetime, _adapt_datetime_epoch)
sqlite3.register_converter("timestamp", _convert_timestamp)


class Record(NamedTuple):
    id: int
    project: str
    task: str | None
    start: datetime.datetime
    stop: datetime.datetime | None


def _record_row_factory(cursor: sqlite3.Cursor, row: tuple) -> Record:
    """Row factory for sqlite connection"""
    return Record(*row)


def get_db_path() -> Path:
    return Path(
        os.getenv("REGISTRE_DB_PATH")
        or platformdirs.user_data_path(appname=APP_NAME, appauthor=APP_AUTHOR)
        / "registre.db"
    )


@contextlib.contextmanager
def connect(
    row_factory: Callable | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager to connect to the db.

    Copied from https://github.com/pre-commit/pre-commit/blob/main/pre_commit/store.py
    """
    with contextlib.closing(
        sqlite3.connect(get_db_path(), detect_types=sqlite3.PARSE_DECLTYPES)
    ) as db:
        if row_factory:
            db.row_factory = row_factory
        # this creates a transaction
        with db:
            yield db


def innit(*, debug: bool) -> None:
    """Initialize the app by crating all the files and configs"""
    db_path = get_db_path()
    if db_path.exists():
        if debug:
            print(f'Using existing db "{db_path}"')
        return
    db_path.parent.mkdir(exist_ok=True)
    with connect() as db:
        db.execute(
            "CREATE TABLE reg ("
            "   id INTEGER NOT NULL PRIMARY KEY,"
            "   project TEXT NOT NULL,"
            "   task TEXT,"
            "   start TIMESTAMP NOT NULL,"
            "   stop TIMESTAMP"
            ")"
        )
    if debug:
        print(f'Created sqlite database at: "{db_path}"\n')


def select_last(project: str | None = None) -> Record | None:
    with connect(_record_row_factory) as db:
        if project:
            last = db.execute(
                "SELECT * FROM reg WHERE project=? ORDER BY start DESC LIMIT 1",
                (project,),
            ).fetchall()
        else:
            last = db.execute(
                "SELECT * FROM reg ORDER BY start DESC LIMIT 1"
            ).fetchall()

    return last[0] if last else None


def select_day(offset: int) -> list[Record]:
    day = datetime.datetime.now(tz=timezone.utc).date() - datetime.timedelta(
        days=offset
    )
    with connect(_record_row_factory) as db:
        records = db.execute(
            "SELECT * FROM reg WHERE date(start, 'unixepoch')=?",
            (day.strftime("%Y-%m-%d"),),
        ).fetchall()
    return records


def select_week(offset: int) -> list[Record]:
    week = datetime.datetime.now(tz=timezone.utc).date() - datetime.timedelta(
        weeks=offset
    )
    start = week - datetime.timedelta(days=week.weekday())
    end = start + datetime.timedelta(days=6)
    with connect(_record_row_factory) as db:
        records = db.execute(
            "SELECT * FROM reg WHERE date(start, 'unixepoch') BETWEEN ? AND ?",
            (start, end),
        ).fetchall()
    return records


def select_month(offset: int) -> list[Record]:
    query_date = datetime.datetime.now(tz=timezone.utc).date()
    for _ in range(offset):
        query_date = datetime.datetime(
            year=query_date.year, month=query_date.month, day=1
        ).date() - datetime.timedelta(days=1)
    with connect(_record_row_factory) as db:
        records = db.execute(
            "SELECT * FROM reg WHERE strftime('%Y-%m', start, 'unixepoch') = ?",
            (query_date.strftime("%Y-%m"),),
        ).fetchall()
    return records


@click.group()
@click.option("--debug/--no-debug", default=False)
def cli(debug: bool = False) -> None:
    """Time tracker CLI <3"""
    innit(debug=debug)


@cli.command()
def info() -> None:
    """Print basic program information and configurations"""
    print(f"Version: {__version__}")
    print(f"Database path: {get_db_path()}")
    with connect() as db:
        projects = db.execute("SELECT DISTINCT project FROM reg").fetchall()
        # COUNT always returns so ti should allways be a list
        (count,) = db.execute("SELECT COUNT(*) FROM reg").fetchall()[0]
    print(f"Tasks registered: {count}")
    print(f"Projects: {', '.join(sorted(p for p, in projects))}")


@cli.command()
@click.argument("project", type=str)
@click.argument("task", type=str)
def start(project: str, task: str) -> None:
    """Start a task for a project"""
    start = datetime.datetime.now(tz=timezone.utc)
    last = select_last()
    if last and last.stop is None:
        print(
            f"Looks like you are already working on "
            f"[bold green]{last.project}[/bold green] "
            f'doing [italic]"{last.task}"[/italic]'
        )

        if click.confirm("Do you want to stop it and start this task?", abort=True):
            stop([], standalone_mode=False)

    with connect() as db:
        db.execute(
            "INSERT INTO reg (project, task, start) VALUES (?, ?, ?)",
            [project, task, start],
        )
        print(f'Started "{task}" for project [bold yellow]{project}[/bold yellow]')


@cli.command()
def stop() -> None:
    """Stop the last started task"""
    last = select_last()
    if not last or last.stop is not None:
        print("Nothing to stop.")
        return

    with connect() as db:
        now = datetime.datetime.now(tz=timezone.utc)
        db.execute("UPDATE reg SET stop=? WHERE id=?", [now, last.id])

    lasted = now - last.start
    rendered_t = now.astimezone().strftime(T_FORMAT)
    print(
        f'Stoped task "{last.task}" for '
        f"[bold yellow]{last.project}[/bold yellow] at {rendered_t}. "
        f"Lasted: {lasted}"
    )


@cli.command()
@click.option("--short", "-s", is_flag=True)
def current(short: bool) -> None:
    """Print the current task"""
    with connect(_record_row_factory) as db:
        query_result = db.execute("SELECT * FROM reg WHERE stop IS NULL").fetchall()
    if query_result:
        current_task = query_result[0]
        if short:
            print(f'"{current_task.task}" on {current_task.project}')
        else:
            print(
                f'Working on "{current_task.task}" for '
                f"[bold yellow]{current_task.project}[/bold yellow]"
                f" since {current_task.start.astimezone().strftime(T_FORMAT)}"
            )


@cli.command()
@click.argument(
    "mode", type=click.Choice(("day", "month", "week"), case_sensitive=False)
)
@click.argument("offset", type=int, default=0, required=False)
def report(mode: str, offset: int = 0) -> None:
    """Make a report of the recorded activity. use OFFSET for previous dates"""

    if mode == "day":
        records = select_day(offset)
    elif mode == "week":
        records = select_week(offset)
    elif mode == "month":
        records = select_month(offset)
    else:
        raise ValueError(f'mode "{mode}" not one of day/week/month')

    table = Table(show_header=False)
    table.add_column("Project", justify="right", style="cyan")
    table.add_column("Total", justify="left", style="magenta")
    for project, group in itertools.groupby(
        sorted(records, key=lambda x: x.project), key=lambda x: x.project
    ):
        project_durations = [r.stop - r.start for r in group if r.stop is not None]
        if project_durations:
            table.add_row(project, str(sum(project_durations, datetime.timedelta())))
    print(table)


@cli.command()
@click.option("--outfile", "-o", type=click.File("w"), default=sys.stdout)
@click.option("--from", "from_", type=click.DateTime())
@click.option("--to", type=click.DateTime())
def export(
    outfile: click.File, from_: datetime.datetime | None, to: datetime.datetime | None
) -> None:
    "Export records as json"
    with connect(_record_row_factory) as db:
        breakpoint()
        if from_ is None and to is None:
            query = db.execute("SELECT * FROM reg")
        elif from_ is not None and to is None:
            query = db.execute("SELECT * FROM reg WHERE start>?", (from_,))
        elif from_ is None and to is not None:
            query = db.execute("SELECT * FROM reg WHERE end<=?", (to,))
        else:
            query = db.execute("SELECT * FROM reg WHERE start>=? and end<=?", (from_,))

        records = query.fetchall()
    json.dump([record._asdict() for record in records], outfile, default=str, indent=2)  # type: ignore


@cli.command()
@click.argument("file", type=click.File("r"), default=sys.stdin)
def import_(file: click.File) -> None:
    """Import an exported json."""
    pass


if __name__ == "__main__":
    cli()
