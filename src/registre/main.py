"""Time tracking app"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Generator
from datetime import datetime
from typing import Callable, NamedTuple

import click
import platformdirs
from rich import print

from registre import __version__

APP_NAME = "registre"
APP_AUTHOR = "biel"
DB_PATH = (
    platformdirs.user_data_path(appname=APP_NAME, appauthor=APP_AUTHOR) / "registre.db"
)
CONFIG_PATH = (
    platformdirs.user_config_path(appname=APP_NAME, appauthor=APP_AUTHOR)
    / "config.yaml"
)
T_FORMAT = "%Y-%m-%d %H:%m:%S"


def adapt_datetime_epoch(d: datetime):
    """Adapt datetime.datetime to Unix timestamp."""
    return int(d.timestamp())


def convert_timestamp(x: float):
    """Convert Unix epoch timestamp to datetime.datetime object."""
    return datetime.fromtimestamp(int(x))


sqlite3.register_adapter(datetime, adapt_datetime_epoch)
sqlite3.register_converter("timestamp", convert_timestamp)


class Record(NamedTuple):
    id: int
    project: str
    task: str | None
    start: datetime
    stop: datetime | None


def record_row_factory(cursor: sqlite3.Cursor, row: tuple) -> Record:
    """Row factory for sqlite connection"""
    return Record(*row)


@contextlib.contextmanager
def connect(
    row_factory: Callable | None = None,
    *,
    db_path: str | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager to connect to the db.

    Copied from https://github.com/pre-commit/pre-commit/blob/main/pre_commit/store.py
    """
    db_path = db_path or DB_PATH
    with contextlib.closing(
        sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    ) as db:
        if row_factory:
            db.row_factory = row_factory
        # this creates a transaction
        with db:
            yield db


def innit() -> None:
    """Innitialize the app by crating all the files and configs"""
    if DB_PATH.exists():
        return
    DB_PATH.parent.mkdir(exist_ok=True)
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
    print(f"Created sqlite database at: {DB_PATH}\n")


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
    if last:
        return last[0]


@click.group()
def cli():
    innit()


@cli.command()
def info() -> None:
    """Print basic program information and configurations"""
    print(f"Version: {__version__}")
    print(f"Database path: {DB_PATH}")
    with connect() as db:
        projects = db.execute("SELECT DISTINCT project FROM reg").fetchall()
    print(f"Projects: {', '.join(sorted(p for p, in projects))}")


@cli.command()
@click.argument("project", type=str)
@click.argument("task", type=str)
def start(project: str, task: str) -> None:
    """start a task"""
    start = datetime.now()
    last_for_project = select_last(project)
    if last_for_project and last_for_project.stop is None:
        print(
            f"Looks like you are already working on "
            f"[bold green]{last_for_project.project}[/bold green] "
            f'and doing [italic]"{last_for_project.task}"[/italic]'
        )
    with connect() as db:
        db.execute(
            "INSERT INTO reg (project, task, start) VALUES (?, ?, ?)",
            [project, task, start],
        )


@cli.command()
def stop() -> None:
    """Stop the last started task"""
    last = select_last()
    if not last or last.stop is not None:
        print("Nothing to stop.")
        return

    with connect() as db:
        now = datetime.now()
        db.execute("UPDATE reg SET stop=? WHERE id=?", [now, last.id])
        print(
            f'Stoped task "{last.task}" for '
            f"[bold yellow]{last.project}[/bold yellow] at {now.strftime(T_FORMAT)}"
        )


@cli.command()
def current() -> None:
    """Print the current task"""
    with connect(record_row_factory) as db:
        rec = db.execute("SELECT * FROM reg WHERE stop IS NULL").fetchall()
    if rec:
        rec = rec[0]
        print(
            f'Working on "{rec.task}" for '
            f"[bold yellow]{rec.project}[/bold yellow] since {rec.start}"
        )


@cli.command()
def report() -> None:
    """Make a report of the recorded activity"""


if __name__ == "__main__":
    cli()
