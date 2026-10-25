import sqlite3
import pytest
from pfquest_db.database import init_db, get_db_stats


def test_init_database(tmp_path):
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    assert db_path.exists()

    stats = get_db_stats(conn)
    expected_tables = [
        "quests",
        "units",
        "unit_spawns",
        "objects",
        "object_spawns",
        "items",
        "item_drops",
        "item_vendors",
        "zones",
        "areatriggers",
        "meta",
        "minimap",
        "professions",
    ]
    for table in expected_tables:
        assert table in stats
        assert stats[table] == 0

    # Verify views exist
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")
    views = {r[0] for r in cur.fetchall()}
    assert "v_quests" in views
    assert "v_spawns" in views
    assert "v_drops" in views
    assert "v_vendors" in views

    conn.close()


def test_views_empty_and_insert(tmp_path):
    db_path = tmp_path / "test_views.db"
    conn = init_db(db_path)

    # Insert a zone, unit, spawn, quest, starter
    conn.execute("INSERT INTO zones (id, name) VALUES (12, 'Elwynn Forest')")
    conn.execute(
        "INSERT INTO units (id, name, min_level, max_level, rank, faction) VALUES (288, 'Jitters', 20, 20, 0, 'AH')"
    )
    conn.execute(
        "INSERT INTO unit_spawns (unit_id, zone_id, x, y, respawn_time) VALUES (288, 12, 45.5, 60.2, 120)"
    )
    conn.execute(
        "INSERT INTO quests (id, title, min_level, quest_level, objective_text, description) "
        "VALUES (5, 'Jitters Growling Gut', 17, 20, 'Speak with Chef Grual.', 'Grual can cook.')"
    )
    conn.execute("INSERT INTO quest_starters (quest_id, starter_type, starter_id) VALUES (5, 'unit', 288)")
    conn.commit()

    # Query v_quests
    cur = conn.execute("SELECT * FROM v_quests WHERE id = 5")
    q = cur.fetchone()
    assert q["title"] == "Jitters Growling Gut"
    assert q["starter_names"] == "Jitters"
    assert q["min_level"] == 17

    # Query v_spawns
    cur = conn.execute("SELECT * FROM v_spawns WHERE entity_id = 288")
    s = cur.fetchone()
    assert s["name"] == "Jitters"
    assert s["zone_name"] == "Elwynn Forest"
    assert s["x"] == 45.5

    conn.close()
