import subprocess
from pathlib import Path
import pytest

from pfquest_db.database import init_db, get_connection
from pfquest_db.importers.questie import import_questie
from pfquest_db.exporters.questie import export_questie


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parent.parent.parent


def test_questie_import_and_export(tmp_path, repo_root):
    questie_dir = repo_root / "Questie" / "Database" / "Wotlk"
    if not questie_dir.exists():
        pytest.skip(f"Questie database not found at {questie_dir}")

    db_path = tmp_path / "questie_test.db"
    conn = init_db(db_path)

    stats = import_questie(questie_dir, conn, flavor="wotlk")
    conn.close()

    assert stats["quests"] > 1000
    assert stats["units"] > 1000
    assert stats["items"] > 1000

    conn2 = get_connection(db_path)
    cur = conn2.execute("SELECT title FROM quests WHERE id = 11")
    row = cur.fetchone()
    assert row is not None
    assert row["title"] == "Riverpaw Gnoll Bounty"

    # Export to Questie format
    export_dir = tmp_path / "exported_questie"
    export_questie(conn2, export_dir, flavor="wotlk")
    conn2.close()

    exported_quest_file = export_dir / "Wotlk" / "wotlkQuestDB.lua"
    assert exported_quest_file.exists()

    # Verify Lua syntax using lua
    res = subprocess.run(
        [
            "lua",
            "-e",
            f"""
            loadstring = loadstring or load
            QuestieDB = {{}}
            QuestieLoader = {{ ImportModule = function() return QuestieDB end }}
            dofile([[{str(exported_quest_file.resolve())}]])
            local qdata = assert(loadstring(QuestieDB.questData))()
            assert(qdata[11] ~= nil, 'Quest 11 not found')
            print('Quest 11 name:', qdata[11][1])
            """,
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Lua validation failed: {res.stderr}"
    assert "Riverpaw Gnoll Bounty" in res.stdout
