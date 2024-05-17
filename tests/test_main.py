import datetime
import io
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console, RenderableType

from registre.main import cli, connect, get_db_path, innit


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "registre.db"


@pytest.fixture(autouse=True)
def set_db_path_env(monkeypatch, db_path):
    monkeypatch.setenv("REGISTRE_DB_PATH", db_path.as_posix())


@pytest.fixture()
def db_innit(db_path):
    innit()
    yield


FAKE_TIME = datetime.datetime(2000, 1, 1, 0, 0, 0)


@pytest.fixture
def patch_datetime_now(monkeypatch):
    class mydatetime(datetime.datetime):
        @classmethod
        def now(cls):
            return FAKE_TIME

    monkeypatch.setattr(datetime, "datetime", mydatetime)


@pytest.fixture
def render_rich_text():
    """Render as rich (with asci scapes and so)
    to be able to compare raw string with terminal outputs"""

    def _render(renderable: RenderableType):
        out_io = io.StringIO()
        console = Console(file=out_io, record=True)
        console.print(renderable)
        return console.export_text(styles=True)

    return _render


def test_db_path(db_path):
    assert get_db_path() == db_path


def test_db_innit(db_path):
    innit()
    assert db_path.exists
    with connect() as db:
        cur = db.execute("SELECT * FROM reg")
    names = [r[0] for r in cur.description]
    assert names == ["id", "project", "task", "start", "stop"]


def test_connect():
    with connect() as db:
        assert db.execute("SELECT 1").fetchall() == [(1,)]


def test_cli_info(db_path, render_rich_text):
    runner = CliRunner()
    res = runner.invoke(cli, ["info"])
    assert res.exit_code == 0
    assert render_rich_text(f"Database path: {db_path}") in res.output


def test_cli_start(patch_datetime_now):
    runner = CliRunner()
    res = runner.invoke(cli, ["start", "project1", "task1"])
    print(res.output)
    assert res.exit_code == 0
    with connect() as db:
        db_res = db.execute("SELECT * FROM reg").fetchall()
    assert db_res == [(1, "project1", "task1", FAKE_TIME, None)]
