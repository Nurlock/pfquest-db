import pytest
from pathlib import Path
from pfquest_db.cli import main
from pfquest_db.database import get_connection, init_db


def test_cli_init_and_stats(tmp_path, capsys):
    db_path = str(tmp_path / "cli_test.db")

    # Test init
    assert main(["init", "--db", db_path]) == 0
    out = capsys.readouterr().out
    assert "Initialized database successfully" in out
    assert Path(db_path).exists()

    # Test stats on empty db
    assert main(["stats", "--db", db_path]) == 0
    out = capsys.readouterr().out
    assert "Database statistics" in out
    assert "quests" in out


def test_cli_query_select_and_update(tmp_path, capsys):
    db_path = str(tmp_path / "cli_query.db")
    main(["init", "--db", db_path])
    capsys.readouterr()

    # Seed data
    conn = get_connection(db_path)
    conn.execute("INSERT INTO units (id, name, min_level) VALUES (1, 'Old Name', 10)")
    conn.commit()
    conn.close()

    # Test SELECT query
    assert main(["query", "--db", db_path, "SELECT id, name FROM units WHERE id = 1"]) == 0
    out = capsys.readouterr().out
    assert "Old Name" in out

    # Test UPDATE query (non-SELECT)
    assert main(["query", "--db", db_path, "UPDATE units SET name = 'New Name' WHERE id = 1"]) == 0
    out = capsys.readouterr().out
    assert "Query executed successfully" in out

    # Verify update was committed
    conn = get_connection(db_path)
    row = conn.execute("SELECT name FROM units WHERE id = 1").fetchone()
    conn.close()
    assert row["name"] == "New Name"


def test_cli_dump_schema(capsys):
    assert main(["dump-schema"]) == 0
    out = capsys.readouterr().out
    assert "CREATE TABLE IF NOT EXISTS quests" in out
    assert "CREATE VIEW v_quests" in out


def test_cli_missing_db_error(tmp_path, capsys):
    missing_db = str(tmp_path / "does_not_exist.db")

    with pytest.raises(SystemExit) as excinfo:
        main(["stats", "--db", missing_db])
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "not found" in err
    # Ensure missing db was not created
    assert not Path(missing_db).exists()
