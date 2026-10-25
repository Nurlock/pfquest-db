"""Tests for pfQuest-Reborn high-performance importer and exporter."""

import sqlite3
from pathlib import Path

from pfquest_db.database import init_db
from pfquest_db.exporters.pfrb import export_pfrb, export_pfrb_lod_module, export_all_lod_modules
from pfquest_db.importers.pfrb import import_pfrb


def test_pfrb_roundtrip(tmp_path: Path):
    db1 = tmp_path / "test1.db"
    conn1 = init_db(db1)

    # Insert test entities
    conn1.execute("INSERT INTO zones (id, name, map_id, x_min, y_min, x_max, y_max) VALUES (1, 'Dun Morogh', 1, 0, 0, 100, 100)")
    conn1.execute("INSERT INTO units (id, name, min_level, max_level, rank, faction) VALUES (100, 'Test Mob', 10, 12, 1, 'H')")
    conn1.execute("INSERT INTO unit_spawns (unit_id, zone_id, x, y, respawn_time) VALUES (100, 1, 25.5, 30.2, 300)")
    conn1.execute("INSERT INTO objects (id, name, faction) VALUES (200, 'Test Chest', 'AH')")
    conn1.execute("INSERT INTO object_spawns (object_id, zone_id, x, y, respawn_time) VALUES (200, 1, 40.0, 50.0, 600)")
    conn1.execute("INSERT INTO items (id, name) VALUES (300, 'Test Ore')")
    conn1.execute("INSERT INTO item_drops (item_id, source_type, source_id, drop_chance) VALUES (300, 'unit', 100, 0.45)")
    conn1.execute("INSERT INTO item_vendors (item_id, unit_id, stock) VALUES (300, 100, 5)")
    conn1.execute("""
        INSERT INTO quests (id, title, min_level, quest_level, required_races, required_classes, objective_text, description)
        VALUES (400, 'Test Quest', 10, 12, 178, 1, 'Kill 5 mobs', 'Go kill them')
    """)
    conn1.execute("INSERT INTO quest_starters (quest_id, starter_type, starter_id) VALUES (400, 'unit', 100)")
    conn1.execute("INSERT INTO quest_finishers (quest_id, finisher_type, finisher_id) VALUES (400, 'unit', 100)")
    conn1.execute("INSERT INTO quest_objectives (quest_id, objective_type, target_id, amount) VALUES (400, 'unit', 100, 5)")
    conn1.execute("INSERT INTO quest_prerequisites (quest_id, pre_quest_id, is_group) VALUES (400, 399, 0)")
    conn1.commit()

    export_dir = tmp_path / "addon_export"
    export_pfrb(conn1, export_dir, flavor="", locale="enUS")
    conn1.close()

    # Verify exported files exist
    assert (export_dir / "db" / "units.lua").exists()
    assert (export_dir / "db" / "objects.lua").exists()
    assert (export_dir / "db" / "items.lua").exists()
    assert (export_dir / "db" / "quests.lua").exists()
    assert (export_dir / "db" / "enUS" / "quests.lua").exists()

    # Re-import into new database
    db2 = tmp_path / "test2.db"
    conn2 = init_db(db2)
    stats = import_pfrb(conn2, export_dir, flavor="", locale="enUS")

    assert stats["units"] == 1
    assert stats["unit_spawns"] == 1
    assert stats["objects"] == 1
    assert stats["object_spawns"] == 1
    assert stats["items"] == 1
    assert stats["item_drops"] == 1
    assert stats["item_vendors"] == 1
    assert stats["quests"] == 1

    # Verify values match exactly
    u = conn2.execute("SELECT id, name, min_level, max_level, rank, faction FROM units WHERE id = 100").fetchone()
    assert tuple(u) == (100, "Test Mob", 10, 12, 1, "H")

    sp = conn2.execute("SELECT x, y, zone_id, respawn_time FROM unit_spawns WHERE unit_id = 100").fetchone()
    assert tuple(sp) == (25.5, 30.2, 1, 300)

    q = conn2.execute("SELECT id, title, min_level, quest_level, required_races, required_classes FROM quests WHERE id = 400").fetchone()
    assert tuple(q) == (400, "Test Quest", 10, 12, 178, 1)

    conn2.close()


def test_export_pfrb_lod_module(tmp_path: Path):
    db = tmp_path / "test_lod.db"
    conn = init_db(db)
    conn.execute("INSERT INTO zones (id, name, map_id) VALUES (1, 'Elwynn Forest', 1)")
    conn.execute("INSERT INTO units (id, name) VALUES (10, 'Hogger')")
    conn.execute("INSERT INTO quests (id, title) VALUES (20, 'Wanted: Hogger')")
    conn.commit()

    dest = tmp_path / "lod_addons"
    mod_dir = export_pfrb_lod_module(conn, dest, flavor="epoch", locale="enUS")
    conn.close()

    assert mod_dir.is_dir()
    assert mod_dir.name == "pfQuest-Reborn-epoch"
    assert (mod_dir / "pfQuest-Reborn-epoch.toc").exists()
    assert (mod_dir / "init" / "data.xml").exists()
    assert (mod_dir / "init" / "enUS.xml").exists()
    assert (mod_dir / "db" / "units.lua").exists()
    assert (mod_dir / "db" / "quests.lua").exists()
    assert (mod_dir / "db" / "enUS" / "quests.lua").exists()

    toc = (mod_dir / "pfQuest-Reborn-epoch.toc").read_text()
    assert "## LoadOnDemand: 1" in toc
    assert "## Dependencies: pfQuest-Reborn" in toc
    assert "Project Epoch" in toc


def test_export_all_lod_modules(tmp_path: Path):
    ref_dir = tmp_path / "ref"
    ref_dir.mkdir()
    for flv in ("vanilla", "epoch", "tbc", "wotlk"):
        conn = init_db(ref_dir / f"{flv}.db")
        conn.execute("INSERT INTO zones (id, name) VALUES (1, 'Test Zone')")
        conn.commit()
        conn.close()

    dest = tmp_path / "addons_all"
    exported = export_all_lod_modules(ref_dir, dest)
    assert len(exported) == 4
    names = {p.name for p in exported}
    assert names == {
        "pfQuest-Reborn-vanilla",
        "pfQuest-Reborn-epoch",
        "pfQuest-Reborn-tbc",
        "pfQuest-Reborn-wotlk",
    }

