"""Tests for human-friendly SQL views and FTS5 search index."""

import pytest
from pfquest_db.database import init_db, rebuild_search_index


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_views.db"
    conn = init_db(db_file)

    # Insert sample test data
    conn.executescript("""
        INSERT INTO zones (id, name, map_id) VALUES (1, 'Elwynn Forest', 30);
        INSERT INTO zones (id, name, map_id) VALUES (2, 'Westfall', 31);

        INSERT INTO units (id, name, min_level, max_level, rank, faction)
        VALUES (100, 'Marshal Dughan', 30, 30, 0, 'Alliance');
        INSERT INTO units (id, name, min_level, max_level, rank, faction)
        VALUES (101, 'Defias Bandit', 10, 11, 0, 'Monster');

        INSERT INTO objects (id, name, faction, faction_id)
        VALUES (200, 'Defias Chest', 'Monster', 0);

        INSERT INTO items (id, name, item_level, required_level)
        VALUES (300, 'Bandit Bandana', 10, 8);

        INSERT INTO unit_spawns (unit_id, zone_id, x, y) VALUES (100, 1, 42.5, 65.0);
        INSERT INTO unit_spawns (unit_id, zone_id, x, y) VALUES (101, 2, 50.0, 55.0);
        INSERT INTO object_spawns (object_id, zone_id, x, y) VALUES (200, 2, 52.0, 58.0);

        INSERT INTO item_drops (item_id, source_type, source_id, drop_chance)
        VALUES (300, 'unit', 101, 80.0);

        INSERT INTO quests (id, title, min_level, quest_level, objective_text, description, next_quest_id)
        VALUES (500, 'Bandit Menace', 10, 12, 'Collect 10 Bandanas', 'Help clear Westfall of bandits.', 501);
        INSERT INTO quests (id, title, min_level, quest_level, objective_text, description)
        VALUES (501, 'The Defias Kingpin', 12, 14, 'Defeat the Kingpin', 'Finish the job.');

        INSERT INTO quest_starters (quest_id, starter_type, starter_id) VALUES (500, 'unit', 100);
        INSERT INTO quest_finishers (quest_id, finisher_type, finisher_id) VALUES (500, 'unit', 100);

        INSERT INTO quest_objectives (quest_id, objective_type, target_id, amount)
        VALUES (500, 'item', 300, 10);
        INSERT INTO quest_objectives (quest_id, objective_type, target_id, amount)
        VALUES (500, 'unit', 101, 5);

        INSERT INTO quest_prerequisites (quest_id, pre_quest_id, is_group) VALUES (501, 500, 0);
    """)
    conn.commit()
    yield conn
    conn.close()


def test_v_quest_details(test_db):
    cur = test_db.execute("SELECT * FROM v_quest_details WHERE quest_id = 500")
    row = dict(cur.fetchone())
    assert row["title"] == "Bandit Menace"
    assert "Marshal Dughan (unit)" in row["starters"]
    assert "Marshal Dughan (unit)" in row["finishers"]
    assert "Collect: Bandit Bandana x10" in row["objectives"]
    assert "Kill: Defias Bandit x5" in row["objectives"]
    assert row["next_quest_id"] == 501
    assert row["next_quest_title"] == "The Defias Kingpin"


def test_v_quest_objectives(test_db):
    cur = test_db.execute("SELECT * FROM v_quest_objectives WHERE quest_id = 500 ORDER BY objective_type")
    rows = [dict(r) for r in cur.fetchall()]
    assert len(rows) == 2
    item_obj = [r for r in rows if r["objective_type"] == "item"][0]
    assert item_obj["target_name"] == "Bandit Bandana"
    assert item_obj["amount"] == 10

    unit_obj = [r for r in rows if r["objective_type"] == "unit"][0]
    assert unit_obj["target_name"] == "Defias Bandit"
    assert unit_obj["amount"] == 5


def test_v_npc_details(test_db):
    cur = test_db.execute("SELECT * FROM v_npc_details WHERE id = 100")
    row = dict(cur.fetchone())
    assert row["name"] == "Marshal Dughan"
    assert "Elwynn Forest" in row["zones"]
    assert row["spawn_count"] == 1
    assert "500: Bandit Menace" in row["quests_started"]


def test_v_item_sources(test_db):
    cur = test_db.execute("SELECT * FROM v_item_sources WHERE item_id = 300")
    row = dict(cur.fetchone())
    assert row["item_name"] == "Bandit Bandana"
    assert row["source_name"] == "Defias Bandit"
    assert row["drop_chance"] == 80.0
    assert "Westfall" in row["drop_zones"]


def test_v_zone_summary(test_db):
    cur = test_db.execute("SELECT * FROM v_zone_summary WHERE zone_id = 2")
    row = dict(cur.fetchone())
    assert row["zone_name"] == "Westfall"
    assert row["unique_units"] == 1
    assert row["unique_objects"] == 1


def test_search_index_fts(test_db):
    indexed = rebuild_search_index(test_db)
    assert indexed > 0

    # Search for quest by keyword in description
    cur = test_db.execute("SELECT * FROM search_index WHERE search_index MATCH 'bandits'")
    rows = [dict(r) for r in cur.fetchall()]
    assert len(rows) >= 1
    assert any(r["name"] == "Bandit Menace" for r in rows)

    # Search for NPC
    cur = test_db.execute("SELECT * FROM search_index WHERE search_index MATCH 'Dughan'")
    rows = [dict(r) for r in cur.fetchall()]
    assert any(r["name"] == "Marshal Dughan" for r in rows)
