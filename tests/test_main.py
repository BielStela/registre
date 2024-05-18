import datetime
import io
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console, RenderableType

from registre.main import (
    T_FORMAT,
    cli,
    connect,
    get_db_path,
    innit,
)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "registre.db"


@pytest.fixture(autouse=True)
def set_db_path_env(monkeypatch, db_path):
    monkeypatch.setenv("REGISTRE_DB_PATH", db_path.as_posix())


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
    innit(debug=False)
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


def test_cli_start(time_machine):
    start_t = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
    time_machine.move_to(start_t)
    runner = CliRunner()
    res = runner.invoke(cli, ["start", "project1", "task1"])
    assert res.exit_code == 0
    with connect() as db:
        db_res = db.execute("SELECT * FROM reg").fetchall()
    assert db_res == [(1, "project1", "task1", start_t, None)]


def test_cli_start_another_stops_previous():
    runner = CliRunner()
    runner.invoke(cli, ["start", "project1", "task1"])
    res = runner.invoke(cli, ["start", "project2", "task2"], input="y")
    print(res.output)


def test_cli_stop(render_rich_text, time_machine):
    runner = CliRunner()
    res = runner.invoke(cli, ["stop"])
    assert res.exit_code == 0
    assert render_rich_text("Nothing to stop.") in res.output
    # time_machine does not mock `astimezone()` with the
    # passed timezone so result can be inconsistent
    # if not mocking with a local timezone since the program is using local timezone
    # to render times.
    # Possibly a problem for future me if I use this with a weird ass configured
    # computer.
    start_t = datetime.datetime(2024, 1, 1, 12, 0, 0).astimezone()
    time_machine.move_to(start_t)
    runner.invoke(cli, ["start", "project1", "task1"])
    stop_t = datetime.datetime(2024, 1, 1, 13, 0, 0).astimezone()
    time_machine.move_to(stop_t)
    res = runner.invoke(cli, ["stop"])
    assert res.exit_code == 0
    assert (
        res.output
        == f'Stoped task "task1" for project1 at {stop_t.strftime(T_FORMAT)}.'
        f" Lasted: {stop_t - start_t}\n"
    )
