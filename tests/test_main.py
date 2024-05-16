import os
import sqlite3
from pathlib import Path

import pytest

from registre.main import innit


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "registre.db"


@pytest.fixture
def dummy_entries(db_path):
    innit(db_path)
    # records = [
    #     Record(
    #         id=1,
    #         project="project1",
    #         task="task1",
    #         start=datetime.datetime(),
    #         end=datetime.datetime(),
    #     )
    # ]
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT ")


def test_db_innit(db_path):
    innit(db_path)
    assert os.path.exists(db_path)
    with sqlite3.connect(db_path) as db:
        cur = db.execute("SELECT * FROM reg")
    names = [r[0] for r in cur.description]
    assert names == ["id", "project", "task", "start", "stop"]
