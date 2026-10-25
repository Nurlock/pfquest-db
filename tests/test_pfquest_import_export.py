import subprocess
from pathlib import Path
import pytest

from pfquest_db.database import init_db, get_connection, get_db_stats
from pfquest_db.importers.pfquest import import_pfquest
from pfquest_db.exporters.pfquest import export_pfquest


@pytest.fixture
def repo_root():
    # pfquest-db parent directory is /home/ourouk/Projects/pfquest
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
