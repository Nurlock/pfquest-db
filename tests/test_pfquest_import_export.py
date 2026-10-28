import subprocess
from pathlib import Path
import pytest

from pfquest_db.database import init_db, get_connection, get_db_stats
from pfquest_db.importers.pfquest import apply_pfquest_overwrites, import_pfquest
from pfquest_db.exporters.pfquest import export_pfquest


@pytest.fixture
def repo_root():
    # pfquest-db parent directory is ~/Projects/Gaming
    return Path(__file__).resolve().parent.parent.parent


def test_pfquest_epoch_import_and_export(tmp_path, repo_root):
    epoch_dir = repo_root / "pfQuest-epoch"
    if not epoch_dir.exists():
        pytest.skip(f"pfQuest-epoch not found at {epoch_dir}")

    db_path = tmp_path / "epoch_test.db"
    conn = init_db(db_path)

    stats = import_pfquest(epoch_dir, conn, flavor="epoch")
    conn.close()

    assert stats["quests"] > 1000
    assert stats["units"] > 500
    assert stats["objects"] > 500
    assert stats["items"] > 1000
    assert stats["unit_spawns"] > 5000

    # Query with a new connection
    conn2 = get_connection(db_path)
    cur = conn2.execute("SELECT title, starter_names FROM v_quests WHERE id = 11")
    row = cur.fetchone()
    assert row is not None
    assert row["title"] == "Riverpaw Gnoll Bounty"
    assert "963" in str(row["starter_names"]) or "Deputy Rainer" in str(row["starter_names"])

    # Export to a temporary directory
    export_dir = tmp_path / "exported_pfquest"
    export_pfquest(conn2, export_dir, flavor="epoch")
    conn2.close()

    assert (export_dir / "db" / "quests-epoch.lua").exists()
    assert (export_dir / "db" / "units-epoch.lua").exists()
    assert (export_dir / "db" / "enUS" / "quests-epoch.lua").exists()

    # Re-import into a secondary database to verify roundtrip fidelity
    roundtrip_db = tmp_path / "roundtrip.db"
    conn_rt = init_db(roundtrip_db)
    rt_stats = import_pfquest(export_dir, conn_rt, flavor="epoch")
    conn_rt.close()

    assert rt_stats["quests"] == stats["quests"]
    assert rt_stats["units"] == stats["units"]
    assert rt_stats["objects"] == stats["objects"]
    assert rt_stats["items"] == stats["items"]


def test_pfquest_idempotent_reimport(tmp_path, repo_root):
    epoch_dir = repo_root / "pfQuest-epoch"
    if not epoch_dir.exists():
        pytest.skip(f"pfQuest-epoch not found at {epoch_dir}")

    db_path = tmp_path / "idempotent.db"
    conn = init_db(db_path)

    # First import
    import_pfquest(epoch_dir, conn, flavor="epoch")
    stats1 = get_db_stats(conn)

    # Second import on the same connection
    import_pfquest(epoch_dir, conn, flavor="epoch")
    stats2 = get_db_stats(conn)
    conn.close()

    # Counts must be identical (no duplicated records)
    assert stats1 == stats2


def test_overlay_replaces_stale_spawns_and_links(tmp_path):
    """Overlay layers replace whole entries (patchtable base[k] = v).

    A stale base spawn must not survive when the overlay redefines the
    entity's coords; stale quest links must not survive a quest rewrite.
    """
    from pfquest_db.importers.pfquest import _purge_entity_children  # noqa: PLC0415

    conn = init_db(tmp_path / "overlay_test.db")
    conn.executescript(
        """
        INSERT INTO zones (id, name) VALUES (1, 'Zone One'), (12, 'Elwynn Forest');
        INSERT INTO units (id, name) VALUES (253, 'William Pestle');
        INSERT INTO unit_spawns (unit_id, zone_id, x, y, respawn_time)
            VALUES (253, 12, 43.3, 65.7, 270);
        INSERT INTO quests (id, title) VALUES (60, 'Kobold Candles'), (61, 'Other');
        INSERT INTO quest_starters (quest_id, starter_type, starter_id)
            VALUES (60, 'unit', 253), (61, 'unit', 253);
        INSERT INTO quest_prerequisites (quest_id, pre_quest_id) VALUES (61, 60);
        INSERT INTO items (id, name) VALUES (772, 'Kobold Candle');
        INSERT INTO item_drops (item_id, source_type, source_id, drop_chance)
            VALUES (772, 'unit', 253, 0.5);
        """
    )
    conn.commit()

    # Simulate an overlay layer redefining unit 253 (moved NPC),
    # quest 60 (changed givers) and item 772 (changed drops).
    _purge_entity_children(conn, "units", [253])
    _purge_entity_children(conn, "quests", [60])
    _purge_entity_children(conn, "items", [772])
    conn.commit()

    # Stale child rows of the overlaid ids are gone...
    assert conn.execute("SELECT COUNT(*) FROM unit_spawns WHERE unit_id = 253").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM quest_starters WHERE quest_id = 60").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM quest_prerequisites WHERE quest_id = 60").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM item_drops WHERE item_id = 772").fetchone()[0] == 0
    # ...but rows owned by OTHER quests referencing these ids survive
    # (they are only purged on entity deletion via overwrites).
    assert conn.execute(
        "SELECT COUNT(*) FROM quest_starters WHERE quest_id = 61 AND starter_id = 253"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM quest_prerequisites WHERE quest_id = 61 AND pre_quest_id = 60"
    ).fetchone()[0] == 1
    conn.close()


def test_overwrites_purge_dangling_references(tmp_path):
    """apply_pfquest_overwrites must remove rows referencing deleted entities.

    Regression test for dead map markers: the entity row was deleted but
    quest starters/finishers/objectives, item drops/vendors, and
    quest-link rows (prereq/next/exclusive) still pointed at it, so
    exporters kept emitting pins for ghosts.
    """
    conn = init_db(tmp_path / "overwrites_test.db")
    conn.executescript(
        """
        INSERT INTO zones (id, name) VALUES (1, 'Test Zone');
        INSERT INTO units (id, name) VALUES (100, 'Doomed NPC'), (200, 'Living NPC');
        INSERT INTO unit_spawns (unit_id, zone_id, x, y) VALUES (100, 1, 10.0, 20.0);
        INSERT INTO objects (id, name) VALUES (300, 'Doomed Object');
        INSERT INTO object_spawns (object_id, zone_id, x, y) VALUES (300, 1, 30.0, 40.0);
        INSERT INTO items (id, name) VALUES (400, 'Doomed Item'), (401, 'Living Item');
        INSERT INTO quests (id, title) VALUES
            (500, 'Doomed Quest'), (501, 'Quest started by doomed NPC'),
            (502, 'Quest needing doomed quest'), (503, 'Quest chained after doomed');
        INSERT INTO quest_starters (quest_id, starter_type, starter_id) VALUES
            (501, 'unit', 100), (501, 'object', 300), (501, 'item', 400), (501, 'unit', 200);
        INSERT INTO quest_finishers (quest_id, finisher_type, finisher_id) VALUES
            (501, 'unit', 100), (501, 'object', 300);
        INSERT INTO quest_objectives (quest_id, objective_type, target_id) VALUES
            (501, 'unit', 100), (501, 'object', 300), (501, 'item', 400);
        INSERT INTO quest_prerequisites (quest_id, pre_quest_id) VALUES (502, 500), (500, 502);
        INSERT INTO quest_exclusive (quest_id, exclusive_quest_id) VALUES (502, 500), (500, 502);
        UPDATE quests SET next_quest_id = 500 WHERE id = 503;
        INSERT INTO item_drops (item_id, source_type, source_id, drop_chance) VALUES
            (401, 'unit', 100, 0.5), (401, 'object', 300, 0.25);
        INSERT INTO item_vendors (item_id, unit_id, stock) VALUES (401, 100, 1), (401, 200, 1);
        """
    )
    conn.commit()

    overwrites = tmp_path / "overwrites.lua"
    overwrites.write_text(
        'pfDB["units"]["data-epoch"][100] = { }\n'
        'pfDB["units"]["enUS-epoch"][100] = ""\n'
        'pfDB["objects"]["data-epoch"][300] = { }\n'
        'pfDB["objects"]["enUS-epoch"][300] = ""\n'
        'pfDB["items"]["data-epoch"][400] = { }\n'
        'pfDB["items"]["enUS-epoch"][400] = ""\n'
        'pfDB["quests"]["data-epoch"][500] = { }\n'
        'pfDB["quests"]["enUS-epoch"][500] = ""\n',
        encoding="utf-8",
    )

    counts = apply_pfquest_overwrites(conn, overwrites)
    assert counts == {"quests": 1, "units": 1, "objects": 1, "items": 1}

    # Entity rows and their own spawns/drops are gone.
    assert conn.execute("SELECT COUNT(*) FROM units WHERE id = 100").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM unit_spawns WHERE unit_id = 100").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM objects WHERE id = 300").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM items WHERE id = 400").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM quests WHERE id = 500").fetchone()[0] == 0

    # No dangling references to removed units / objects / items.
    assert conn.execute(
        "SELECT COUNT(*) FROM quest_starters WHERE starter_id IN (100, 300, 400)"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM quest_finishers WHERE finisher_id IN (100, 300)"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM quest_objectives WHERE target_id IN (100, 300, 400)"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM item_drops WHERE source_id IN (100, 300)"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM item_vendors WHERE unit_id = 100"
    ).fetchone()[0] == 0

    # Quest-link rows touching the removed quest are gone / cleared.
    assert conn.execute(
        "SELECT COUNT(*) FROM quest_prerequisites WHERE quest_id = 500 OR pre_quest_id = 500"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM quest_exclusive WHERE quest_id = 500 OR exclusive_quest_id = 500"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT next_quest_id FROM quests WHERE id = 503"
    ).fetchone()[0] is None

    # Rows for living entities survive untouched.
    assert conn.execute("SELECT COUNT(*) FROM units WHERE id = 200").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM quest_starters WHERE quest_id = 501 AND starter_type = 'unit' AND starter_id = 200"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM item_vendors WHERE item_id = 401 AND unit_id = 200"
    ).fetchone()[0] == 1
    conn.close()


def test_pfquest_base_and_overlay_import(tmp_path, repo_root):
    base_dir = repo_root / "pfQuest-Reforged"
    epoch_dir = repo_root / "pfQuest-epoch"
    if not base_dir.exists() or not epoch_dir.exists():
        pytest.skip("pfQuest-Reforged or pfQuest-epoch not found")

    db_path = tmp_path / "merged.db"
    conn = init_db(db_path)
    stats = import_pfquest(epoch_dir, conn, flavor="epoch", base_src=base_dir)

    # Quests should be merged (over 5,000 quests)
    assert stats["quests"] > 5000
    # Quests with NULL/empty title should be 0
    cur = conn.execute("SELECT COUNT(*) FROM quests WHERE title IS NULL OR title = ''")
    assert cur.fetchone()[0] == 0
    conn.close()
