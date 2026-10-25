"""Questie Lua database importer."""

import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

from ..lua_bridge import iter_lua_table_entries


QUESTIE_PRE_CODE = """
QuestieDB = {}
QuestieLoader = { ImportModule = function() return QuestieDB end }
"""


def _get_field(data: Any, idx_1_based: int) -> Any:
    """Retrieve field by 1-based index from either list or sparse dictionary."""
    if isinstance(data, list):
        idx_0 = idx_1_based - 1
        return data[idx_0] if 0 <= idx_0 < len(data) else None
    if isinstance(data, dict):
        val = data.get(str(idx_1_based))
        if val is None:
            val = data.get(idx_1_based)
        return val
    return None


def _id_list(val) -> list[int]:
    """Extract list of integer IDs from flat, nested, or tuple lists."""
    if val is None:
        return []
    if isinstance(val, (int, float)):
        return [int(val)]
    if isinstance(val, dict):
        val = list(val.values())
    if not isinstance(val, list):
        return []
    res = []
    for item in val:
        if isinstance(item, (int, float)):
            res.append(int(item))
        elif isinstance(item, (list, dict)):
            first = _get_field(item, 1) if isinstance(item, dict) else (item[0] if item else None)
            if isinstance(first, (int, float)):
                res.append(int(first))
    return res


def _iter_spawns(spawns: Any):
    """Yield (zone_id, x, y) from either a dict {zone_id: [[x, y], ...]} or 1-based list."""
    if isinstance(spawns, dict):
        for zid_str, pts in spawns.items():
            try:
                zid = int(zid_str)
            except (ValueError, TypeError):
                continue
            if isinstance(pts, list):
                for pt in pts:
                    if isinstance(pt, list) and len(pt) >= 2:
                        try:
                            x, y = float(pt[0]), float(pt[1])
                            if x >= 0 and y >= 0:
                                yield zid, x, y
                        except (ValueError, TypeError):
                            pass
    elif isinstance(spawns, list):
        for idx_0, pts in enumerate(spawns):
            zid = idx_0 + 1
            if isinstance(pts, list):
                for pt in pts:
                    if isinstance(pt, list) and len(pt) >= 2:
                        try:
                            x, y = float(pt[0]), float(pt[1])
                            if x >= 0 and y >= 0:
                                yield zid, x, y
                        except (ValueError, TypeError):
                            pass


def import_questie(
    base_dir: str | Path,
    conn: sqlite3.Connection,
    flavor: str = "wotlk",
) -> dict[str, int]:
    """
    Import Questie database files from base_dir into SQLite database conn.
    base_dir can be the directory containing wotlkQuestDB.lua (e.g. Questie/Database/Wotlk)
    or the parent Questie/Database directory.
    """
    base_path = Path(base_dir)
    if (base_path / "Wotlk").exists():
        target_dir = base_path / "Wotlk"
        parent_dir = base_path
    elif (base_path / f"{flavor}QuestDB.lua").exists():
        target_dir = base_path
        parent_dir = base_path.parent
    else:
        target_dir = base_path
        parent_dir = base_path

    stats = {
        "zones": 0,
        "units": 0,
        "unit_spawns": 0,
        "objects": 0,
        "object_spawns": 0,
        "items": 0,
        "item_drops": 0,
        "item_vendors": 0,
        "quests": 0,
    }

    # 1. Zone Names from areaIdToUiMapId.lua if available
    area_map_file = parent_dir / "Zones" / "data" / "areaIdToUiMapId.lua"
    if not area_map_file.exists():
        matches = list(parent_dir.glob("**/areaIdToUiMapId.lua"))
        if matches:
            area_map_file = matches[0]

    zone_rows = []
    if area_map_file.exists():
        pattern = re.compile(r"^\s*\[(\d+)\]\s*=\s*\d+,\s*--\s*(.+)\s*$")
        with open(area_map_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pattern.match(line)
                if m:
                    zid = int(m.group(1))
                    zname = m.group(2).strip()
                    zone_rows.append((zid, zname, None, None, None, None, None))
        if zone_rows:
            conn.executemany(
                """
                INSERT INTO zones (id, name, map_id, x_min, x_max, y_min, y_max)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = COALESCE(excluded.name, zones.name)
                """,
                zone_rows,
            )
            stats["zones"] = len(zone_rows)

    # 2. NPCs / Units
    npc_file = target_dir / f"{flavor}NpcDB.lua"
    if not npc_file.exists():
        npc_file = target_dir / "npcDB.lua"

    unit_rows = []
    unit_spawn_rows = []
    if npc_file.exists():
        expr = "assert(loadstring(QuestieDB.npcData))()"
        for uid, ndata in iter_lua_table_entries(npc_file, expr, QUESTIE_PRE_CODE):
            if not isinstance(ndata, (list, dict)):
                continue
            uid_int = int(uid)
            name = _get_field(ndata, 1)
            min_l = _get_field(ndata, 4)
            max_l = _get_field(ndata, 5)
            rank = _get_field(ndata, 6) or 0
            fac = _get_field(ndata, 13)
            sub_name = _get_field(ndata, 14)
            npc_flags = _get_field(ndata, 15) or 0

            unit_rows.append((uid_int, name, min_l, max_l, rank, fac, sub_name, npc_flags))

            # Spawns: { [zoneID] = { {x, y}, ... } } at index 7
            spawns = _get_field(ndata, 7)
            if spawns:
                for zid, x, y in _iter_spawns(spawns):
                    unit_spawn_rows.append((uid_int, zid, x, y, 0))

        if unit_rows:
            conn.executemany(
                """
                INSERT INTO units (id, name, min_level, max_level, rank, faction, sub_name, npc_flags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = COALESCE(excluded.name, units.name),
                    min_level = COALESCE(excluded.min_level, units.min_level),
                    max_level = COALESCE(excluded.max_level, units.max_level),
                    rank = COALESCE(excluded.rank, units.rank),
                    faction = COALESCE(excluded.faction, units.faction),
                    sub_name = COALESCE(excluded.sub_name, units.sub_name),
                    npc_flags = COALESCE(excluded.npc_flags, units.npc_flags)
                """,
                unit_rows,
            )
            stats["units"] = len(unit_rows)

        if unit_spawn_rows:
            spawn_zones = {r[1] for r in unit_spawn_rows}
            cur_zones = {r[0] for r in conn.execute("SELECT id FROM zones").fetchall()}
            missing_z = spawn_zones - cur_zones
            if missing_z:
                conn.executemany(
                    "INSERT OR IGNORE INTO zones (id, name) VALUES (?, ?)",
                    [(z, f"Zone {z}") for z in missing_z],
                )

            conn.executemany(
                """
                INSERT OR IGNORE INTO unit_spawns (unit_id, zone_id, x, y, respawn_time)
                VALUES (?, ?, ?, ?, ?)
                """,
                unit_spawn_rows,
            )
            stats["unit_spawns"] = len(unit_spawn_rows)

    # 3. Objects
    obj_file = target_dir / f"{flavor}ObjectDB.lua"
    if not obj_file.exists():
        obj_file = target_dir / "objectDB.lua"

    obj_rows = []
    obj_spawn_rows = []
    if obj_file.exists():
        expr = "assert(loadstring(QuestieDB.objectData))()"
        for oid, odata in iter_lua_table_entries(obj_file, expr, QUESTIE_PRE_CODE):
            if not isinstance(odata, (list, dict)):
                continue
            oid_int = int(oid)
            name = _get_field(odata, 1)
            fac_id = _get_field(odata, 6)

            obj_rows.append((oid_int, name, None, fac_id))

            # Spawns at index 4
            spawns = _get_field(odata, 4)
            if spawns:
                for zid, x, y in _iter_spawns(spawns):
                    obj_spawn_rows.append((oid_int, zid, x, y, 0))

        if obj_rows:
            conn.executemany(
                """
                INSERT INTO objects (id, name, faction, faction_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = COALESCE(excluded.name, objects.name),
                    faction_id = COALESCE(excluded.faction_id, objects.faction_id)
                """,
                obj_rows,
            )
            stats["objects"] = len(obj_rows)

        if obj_spawn_rows:
            spawn_zones = {r[1] for r in obj_spawn_rows}
            cur_zones = {r[0] for r in conn.execute("SELECT id FROM zones").fetchall()}
            missing_z = spawn_zones - cur_zones
            if missing_z:
                conn.executemany(
                    "INSERT OR IGNORE INTO zones (id, name) VALUES (?, ?)",
                    [(z, f"Zone {z}") for z in missing_z],
                )

            conn.executemany(
                """
                INSERT OR IGNORE INTO object_spawns (object_id, zone_id, x, y, respawn_time)
                VALUES (?, ?, ?, ?, ?)
                """,
                obj_spawn_rows,
            )
            stats["object_spawns"] = len(obj_spawn_rows)

    # 4. Items
    item_file = target_dir / f"{flavor}ItemDB.lua"
    if not item_file.exists():
        item_file = target_dir / "itemDB.lua"

    item_rows = []
    drop_rows = []
    vendor_rows = []
    if item_file.exists():
        expr = "assert(loadstring(QuestieDB.itemData))()"
        for iid, idata in iter_lua_table_entries(item_file, expr, QUESTIE_PRE_CODE):
            if not isinstance(idata, (list, dict)):
                continue
            iid_int = int(iid)
            name = _get_field(idata, 1)
            flags = _get_field(idata, 7)
            food = _get_field(idata, 8)
            ilvl = _get_field(idata, 9)
            req_lvl = _get_field(idata, 10)
            ammo = _get_field(idata, 11)
            cls_id = _get_field(idata, 12)
            subcls_id = _get_field(idata, 13)
            spell = _get_field(idata, 16)

            item_rows.append(
                (iid_int, name, ilvl, req_lvl, cls_id, subcls_id, food, ammo, flags, spell)
            )

            # npcDrops (index 2)
            npc_drops = _id_list(_get_field(idata, 2))
            for uid in npc_drops:
                drop_rows.append((iid_int, "unit", uid, 0.0))

            # objectDrops (index 3)
            obj_drops = _id_list(_get_field(idata, 3))
            for oid in obj_drops:
                drop_rows.append((iid_int, "object", oid, 0.0))

            # vendors (index 14)
            vendors = _id_list(_get_field(idata, 14))
            for vid in vendors:
                vendor_rows.append((iid_int, vid, 0))

        if item_rows:
            conn.executemany(
                """
                INSERT INTO items (
                    id, name, item_level, required_level, class_id, subclass_id,
                    food_type, ammo_type, flags, teaches_spell
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = COALESCE(excluded.name, items.name),
                    item_level = COALESCE(excluded.item_level, items.item_level),
                    required_level = COALESCE(excluded.required_level, items.required_level),
                    class_id = COALESCE(excluded.class_id, items.class_id),
                    subclass_id = COALESCE(excluded.subclass_id, items.subclass_id),
                    flags = COALESCE(excluded.flags, items.flags),
                    teaches_spell = COALESCE(excluded.teaches_spell, items.teaches_spell)
                """,
                item_rows,
            )
            stats["items"] = len(item_rows)

        if drop_rows:
            conn.executemany(
                """
                INSERT OR IGNORE INTO item_drops (item_id, source_type, source_id, drop_chance)
                VALUES (?, ?, ?, ?)
                """,
                drop_rows,
            )
            stats["item_drops"] = len(drop_rows)

        if vendor_rows:
            v_uids = {r[1] for r in vendor_rows}
            cur_u = {r[0] for r in conn.execute("SELECT id FROM units").fetchall()}
            missing_u = v_uids - cur_u
            if missing_u:
                conn.executemany(
                    "INSERT OR IGNORE INTO units (id, name) VALUES (?, ?)",
                    [(u, f"Unknown Unit {u}") for u in missing_u],
                )

            conn.executemany(
                """
                INSERT OR IGNORE INTO item_vendors (item_id, unit_id, stock)
                VALUES (?, ?, ?)
                """,
                vendor_rows,
            )
            stats["item_vendors"] = len(vendor_rows)

    # 5. Quests
    quest_file = target_dir / f"{flavor}QuestDB.lua"
    if not quest_file.exists():
        quest_file = target_dir / "questDB.lua"

    quest_rows = []
    starter_rows = []
    finisher_rows = []
    objective_rows = []
    prereq_rows = []
    exclusive_rows = []

    if quest_file.exists():
        expr = "assert(loadstring(QuestieDB.questData))()"
        for qid, qdata in iter_lua_table_entries(quest_file, expr, QUESTIE_PRE_CODE):
            if not isinstance(qdata, (list, dict)):
                continue
            qid_int = int(qid)
            title = _get_field(qdata, 1)
            req_lvl = _get_field(qdata, 4)
            qlvl = _get_field(qdata, 5)
            races = _get_field(qdata, 6)
            classes = _get_field(qdata, 7)

            # objectivesText (index 8): table or list of strings
            obj_texts = _get_field(qdata, 8)
            if isinstance(obj_texts, dict):
                obj_texts = list(obj_texts.values())
            obj_text = " ".join(s for s in obj_texts if isinstance(s, str)) if isinstance(obj_texts, list) else None

            source_item = _get_field(qdata, 11)
            next_q = _get_field(qdata, 22)
            qflags = _get_field(qdata, 23)
            spflags = _get_field(qdata, 24)

            # requiredSkill (index 18): {skill, value}
            req_skill = _get_field(qdata, 18)
            sk_id = _get_field(req_skill, 1) if req_skill else None
            sk_val = _get_field(req_skill, 2) if req_skill else None

            # requiredMinRep (index 19): {faction, value}
            min_rep = _get_field(qdata, 19)
            min_rep_fac = _get_field(min_rep, 1) if min_rep else None
            min_rep_val = _get_field(min_rep, 2) if min_rep else None

            # requiredMaxRep (index 20): {faction, value}
            max_rep = _get_field(qdata, 20)
            max_rep_fac = _get_field(max_rep, 1) if max_rep else None
            max_rep_val = _get_field(max_rep, 2) if max_rep else None

            quest_rows.append(
                (
                    qid_int,
                    title,
                    req_lvl,
                    qlvl,
                    races,
                    classes,
                    obj_text,
                    None,
                    next_q,
                    sk_id,
                    sk_val,
                    min_rep_fac,
                    min_rep_val,
                    max_rep_fac,
                    max_rep_val,
                    None,
                    source_item,
                    spflags,
                    qflags,
                )
            )

            # Starters: startedBy (index 2): {[1]=creatures, [2]=objects, [3]=items}
            started_by = _get_field(qdata, 2)
            if started_by:
                for uid in _id_list(_get_field(started_by, 1)):
                    starter_rows.append((qid_int, "unit", uid))
                for oid in _id_list(_get_field(started_by, 2)):
                    starter_rows.append((qid_int, "object", oid))
                for iid in _id_list(_get_field(started_by, 3)):
                    starter_rows.append((qid_int, "item", iid))

            # Finishers: finishedBy (index 3): {[1]=creatures, [2]=objects}
            finished_by = _get_field(qdata, 3)
            if finished_by:
                for uid in _id_list(_get_field(finished_by, 1)):
                    finisher_rows.append((qid_int, "unit", uid))
                for oid in _id_list(_get_field(finished_by, 2)):
                    finisher_rows.append((qid_int, "object", oid))

            # Objectives (index 10): {[1]=creatures, [2]=objects, [3]=items, ...}
            objectives = _get_field(qdata, 10)
            if objectives:
                for item in _id_list(_get_field(objectives, 1)):
                    objective_rows.append((qid_int, "unit", item, 0, None, None))
                for item in _id_list(_get_field(objectives, 2)):
                    objective_rows.append((qid_int, "object", item, 0, None, None))
                for item in _id_list(_get_field(objectives, 3)):
                    objective_rows.append((qid_int, "item", item, 0, None, None))

            # requiredSourceItems (index 21)
            req_items = _id_list(_get_field(qdata, 21))
            for iid in req_items:
                objective_rows.append((qid_int, "itemreq", iid, 0, None, None))

            # Prerequisites: preQuestSingle (index 13), preQuestGroup (index 12)
            pre_single = _id_list(_get_field(qdata, 13))
            for pq in pre_single:
                prereq_rows.append((qid_int, pq, 0))

            pre_group = _id_list(_get_field(qdata, 12))
            for pq in pre_group:
                prereq_rows.append((qid_int, pq, 1))

            # exclusiveTo (index 16)
            excl = _id_list(_get_field(qdata, 16))
            for eq in excl:
                exclusive_rows.append((qid_int, eq))

        if quest_rows:
            conn.executemany(
                """
                INSERT INTO quests (
                    id, title, min_level, quest_level, required_races, required_classes,
                    objective_text, description, next_quest_id, required_skill_id,
                    required_skill_value, required_min_rep_faction, required_min_rep_value,
                    required_max_rep_faction, required_max_rep_value, event_id,
                    source_item_id, special_flags, quest_flags
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = COALESCE(excluded.title, quests.title),
                    min_level = COALESCE(excluded.min_level, quests.min_level),
                    quest_level = COALESCE(excluded.quest_level, quests.quest_level),
                    required_races = COALESCE(excluded.required_races, quests.required_races),
                    required_classes = COALESCE(excluded.required_classes, quests.required_classes),
                    objective_text = COALESCE(excluded.objective_text, quests.objective_text),
                    next_quest_id = COALESCE(excluded.next_quest_id, quests.next_quest_id),
                    required_skill_id = COALESCE(excluded.required_skill_id, quests.required_skill_id),
                    required_skill_value = COALESCE(excluded.required_skill_value, quests.required_skill_value),
                    required_min_rep_faction = COALESCE(excluded.required_min_rep_faction, quests.required_min_rep_faction),
                    required_min_rep_value = COALESCE(excluded.required_min_rep_value, quests.required_min_rep_value),
                    required_max_rep_faction = COALESCE(excluded.required_max_rep_faction, quests.required_max_rep_faction),
                    required_max_rep_value = COALESCE(excluded.required_max_rep_value, quests.required_max_rep_value),
                    source_item_id = COALESCE(excluded.source_item_id, quests.source_item_id),
                    special_flags = COALESCE(excluded.special_flags, quests.special_flags),
                    quest_flags = COALESCE(excluded.quest_flags, quests.quest_flags)
                """,
                quest_rows,
            )
            stats["quests"] = len(quest_rows)

        if starter_rows:
            conn.executemany(
                """
                INSERT OR IGNORE INTO quest_starters (quest_id, starter_type, starter_id)
                VALUES (?, ?, ?)
                """,
                starter_rows,
            )

        if finisher_rows:
            conn.executemany(
                """
                INSERT OR IGNORE INTO quest_finishers (quest_id, finisher_type, finisher_id)
                VALUES (?, ?, ?)
                """,
                finisher_rows,
            )

        if objective_rows:
            conn.executemany(
                """
                INSERT OR IGNORE INTO quest_objectives (quest_id, objective_type, target_id, amount, text, icon)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                objective_rows,
            )

        if prereq_rows:
            conn.executemany(
                """
                INSERT OR IGNORE INTO quest_prerequisites (quest_id, pre_quest_id, is_group)
                VALUES (?, ?, ?)
                """,
                prereq_rows,
            )

        if exclusive_rows:
            conn.executemany(
                """
                INSERT OR IGNORE INTO quest_exclusive (quest_id, exclusive_quest_id)
                VALUES (?, ?)
                """,
                exclusive_rows,
            )

    conn.commit()
    return stats
