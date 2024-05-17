"""Time tracking app"""

from __future__ import annotations

import contextlib
import datetime
import itertools
import os
import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Callable, NamedTuple

import click
import platformdirs
from rich import print
from rich.table import Table

from registre import __version__

APP_NAME = "registre"
APP_AUTHOR = "biel"

T_FORMAT = "%Y-%m-%d %H:%m:%S"


def adapt_datetime_epoch(d: datetime.datetime) -> int:
    """Adapt datetime.datetime to Unix timestamp."""
    return int(d.timestamp())


def convert_timestamp(x: bytes) -> datetime.datetime:
    """Convert Unix epoch timestamp to datetime.datetime object."""
    return datetime.datetime.fromtimestamp(int(x))


sqlite3.register_adapter(datetime.datetime, adapt_datetime_epoch)
sqlite3.register_converter("timestamp", convert_timestamp)


class Record(NamedTuple):
    id: int
    project: str
    task: str | None
    start: datetime.datetime
    stop: datetime.datetime | None


def record_row_factory(cursor: sqlite3.Cursor, row: tuple) -> Record:
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


def innit(debug: bool = False) -> None:
    """Innitialize the app by crating all the files and configs"""
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
    with connect(record_row_factory) as db:
        if project:
            last = db.execute(
                "SELECT * FROM reg WHERE project=? ORDER BY start DESC LIMIT 1",
                [project],
            ).fetchall()
        else:
            last = db.execute(
                "SELECT * FROM reg ORDER BY start DESC LIMIT 1"
            ).fetchall()

    return last[0] if last else None


def select_day(offset: int) -> list[Record]:
    day = datetime.datetime.now().date() - datetime.timedelta(days=offset)
    with connect(record_row_factory) as db:
        records = db.execute(
            "SELECT * FROM reg WHERE date(start, 'unixepoch')=?",
            [day.strftime("%Y-%m-%d")],
        ).fetchall()
    return records


def select_week(offset: int) -> list[Record]:
    week = datetime.datetime.now().date() - datetime.timedelta(weeks=offset)
    start = week - datetime.timedelta(days=week.weekday())
    end = start + datetime.timedelta(days=6)
    with connect(record_row_factory) as db:
        records = db.execute(
            "SELECT * FROM reg WHERE date(start, 'unixepoch') BETWEEN ? AND ?",
            [start, end],
        ).fetchall()
    return records


def select_month(offset: int) -> list[Record]:
    query_date = datetime.datetime.now().date()
    for _ in range(offset):
        query_date = datetime.datetime(
            year=query_date.year, month=query_date.month, day=1
        ).date() - datetime.timedelta(days=1)
    with connect(record_row_factory) as db:
        records = db.execute(
            "SELECT * FROM reg WHERE strftime('%Y-%m', start, 'unixepoch') = ?",
            [query_date.strftime("%Y-%m")],
        ).fetchall()
    return records


@click.group()
@click.option("--debug/--no-debug", default=False)
def cli(debug):
    """Time tracker CLI <3"""
    innit(debug)


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
    start = datetime.datetime.now()
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
        now = datetime.datetime.now()
        db.execute("UPDATE reg SET stop=? WHERE id=?", [now, last.id])

    lasted = now - last.start
    print(
        f'Stoped task "{last.task}" for '
        f"[bold yellow]{last.project}[/bold yellow] at {now.strftime(T_FORMAT)}. "
        f"Lasted: {lasted}"
    )


@cli.command()
@click.option("--short", "-s", is_flag=True)
def current(short: bool) -> None:
    """Print the current task"""
    with connect(record_row_factory) as db:
        query_result = db.execute("SELECT * FROM reg WHERE stop IS NULL").fetchall()
    if query_result:
        current_task = query_result[0]
        if short:
            print(f'"{current_task.task}" on {current_task.project}')
        else:
            print(
                f'Working on "{current_task.task}" for '
                f"[bold yellow]{current_task.project}[/bold yellow]"
                f" since {current_task.start}"
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


if __name__ == "__main__":
    cli()
