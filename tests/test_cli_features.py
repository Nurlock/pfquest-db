"""Tests for CLI formatting and search command."""

import json
from pfquest_db.cli import main
from pfquest_db.database import init_db, rebuild_search_index


def test_cli_query_formats(tmp_path, capsys):
    db_file = tmp_path / "cli_test.db"
    conn = init_db(db_file)
    conn.execute("INSERT INTO zones (id, name, map_id) VALUES (1, 'Durotar', 14);")
    conn.commit()
    conn.close()

    # Test JSON output
    ret = main(["query", "--db", str(db_file), "SELECT id, name FROM zones", "--format", "json"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data) == 1
    assert data[0]["name"] == "Durotar"

    # Test Markdown output
    ret = main(["query", "--db", str(db_file), "SELECT id, name FROM zones", "--format", "markdown"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "| id | name |" in captured.out
    assert "| 1 | Durotar |" in captured.out


def test_cli_search_command(tmp_path, capsys):
    db_file = tmp_path / "search_test.db"
    conn = init_db(db_file)
    conn.execute("INSERT INTO quests (id, title, description) VALUES (10, 'Find Mankrik', 'Help Mankrik find his wife.');")
    conn.commit()
    rebuild_search_index(conn)
    conn.close()

    ret = main(["search", "--db", str(db_file), "Mankrik", "--format", "json"])
    assert ret == 0
    captured = capsys.readouterr()
    results = json.loads(captured.out)
    assert len(results) == 1
    assert results[0]["name"] == "Find Mankrik"
