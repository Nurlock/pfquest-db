"""pfQuest Lua database importer."""

import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

from ..lua_bridge import iter_lua_table_entries, load_lua_table


PRE_CODE_TEMPLATE = """
pfDB = {
    quests = {},
    units = {},
    objects = {},
    items = {},
    zones = {},
    areatrigger = {},
    minimap = {},
    ["quests-itemreq"] = {},
    refloot = {},
    professions = {},
}
"""


def _as_list(val) -> list[int]:
    if val is None:
        return []
    if isinstance(val, (int, float)):
        return [int(val)]
    if isinstance(val, dict):
        val = list(val.values())
    if isinstance(val, list):
        return [int(x) for x in val if isinstance(x, (int, float))]
    return []


def _parse_level_range(lvl_val) -> tuple[Optional[int], Optional[int]]:
    if lvl_val is None:
        return None, None
    if isinstance(lvl_val, int):
        return lvl_val, lvl_val
    if isinstance(lvl_val, str):
        if "-" in lvl_val:
            parts = lvl_val.split("-")
            try:
                return int(parts[0].strip()), int(parts[1].strip())
            except ValueError:
                return None, None
        try:
            val = int(lvl_val.strip())
            return val, val
        except ValueError:
            return None, None
    return None, None


def apply_pfquest_overwrites(conn: sqlite3.Connection, overwrites_path: str | Path) -> dict[str, int]:
    """Parse and apply pfQuest-epoch overwrites.lua to remove reworked/deleted entities."""
    path = Path(overwrites_path)
    if not path.exists():
        return {}

    lua_code = f"""
    local pfDB = {{
        units = {{ ["data-epoch"] = {{}}, ["enUS-epoch"] = {{}} }},
        quests = {{ ["data-epoch"] = {{}}, ["enUS-epoch"] = {{}} }},
        items = {{ ["data-epoch"] = {{}}, ["enUS-epoch"] = {{}} }},
        objects = {{ ["data-epoch"] = {{}}, ["enUS-epoch"] = {{}} }},
    }}
    local f = loadfile("{path.resolve()}")
    if f then
        local env = setmetatable({{pfDB = pfDB}}, {{__index = _G}})
        setfenv(f, env)
        pcall(f)
    end
    for cat, tbl in pairs(pfDB) do
        for id, _ in pairs(tbl["data-epoch"] or {{}}) do
            io.write(cat .. ":" .. tostring(id) .. string.char(10))
        end
    end
    """
    proc = subprocess.run(["lua5.1", "-e", lua_code], capture_output=True, text=True, check=True)
    removed: dict[str, list[tuple[int]]] = {"quests": [], "units": [], "objects": [], "items": []}
    for line in proc.stdout.splitlines():
        if ":" in line:
            cat, sid = line.strip().split(":", 1)
            if cat in removed and sid.isdigit():
                removed[cat].append((int(sid),))

    counts: dict[str, int] = {}
    if removed["quests"]:
        conn.executemany("DELETE FROM quests WHERE id = ?", removed["quests"])
        conn.executemany("DELETE FROM quest_starters WHERE quest_id = ?", removed["quests"])
        conn.executemany("DELETE FROM quest_finishers WHERE quest_id = ?", removed["quests"])
        conn.executemany("DELETE FROM quest_objectives WHERE quest_id = ?", removed["quests"])
        conn.executemany("DELETE FROM quest_prerequisites WHERE quest_id = ?", removed["quests"])
        conn.executemany("DELETE FROM quest_exclusive WHERE quest_id = ?", removed["quests"])
        counts["quests"] = len(removed["quests"])
    if removed["units"]:
        conn.executemany("DELETE FROM units WHERE id = ?", removed["units"])
        conn.executemany("DELETE FROM unit_spawns WHERE unit_id = ?", removed["units"])
        counts["units"] = len(removed["units"])
    if removed["objects"]:
        conn.executemany("DELETE FROM objects WHERE id = ?", removed["objects"])
        conn.executemany("DELETE FROM object_spawns WHERE object_id = ?", removed["objects"])
        counts["objects"] = len(removed["objects"])
    if removed["items"]:
        conn.executemany("DELETE FROM items WHERE id = ?", removed["items"])
        conn.executemany("DELETE FROM item_drops WHERE item_id = ?", removed["items"])
        conn.executemany("DELETE FROM item_vendors WHERE item_id = ?", removed["items"])
        counts["items"] = len(removed["items"])

    conn.commit()
    return counts


def import_pfquest(
    base_dir: str | Path,
    conn: sqlite3.Connection,
    flavor: str = "epoch",
    locale: str = "enUS",
    base_src: Optional[str | Path] = None,
) -> dict[str, int]:
    """
    Import pfQuest database files from base_dir into SQLite database conn.
    flavor: 'epoch', 'tbc', 'wotlk', or '' (for vanilla/classic).
    If base_src is provided, the base database is imported first with flavor='',
    then the flavor overlay from base_dir is applied on top.
    """
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
        "areatriggers": 0,
        "meta": 0,
        "minimap": 0,
        "professions": 0,
    }

    if base_src:
        base_stats = import_pfquest(base_src, conn, flavor="", locale=locale)
        for k, v in base_stats.items():
            stats[k] += v

    base_path = Path(base_dir)
    suffix = f"-{flavor}" if flavor else ""
    loc_suffix = f"-{flavor}" if flavor else ""

    data_dir = base_path / "db"
    loc_dir = data_dir / locale

    suffix_clean = suffix if suffix else ""

    # 1. Zones
    zone_names: dict[int, str] = {}
    zone_loc_file = loc_dir / f"zones{loc_suffix}.lua"
    if zone_loc_file.exists():
        loc_key = f"{locale}{loc_suffix}"
        expr = f'pfDB["zones"]["{loc_key}"] or pfDB["zones"]["{locale}"]'
        for zid, name in iter_lua_table_entries(zone_loc_file, expr, PRE_CODE_TEMPLATE):
            zone_names[int(zid)] = str(name)

    zone_data_file = data_dir / f"zones{suffix}.lua"
    zone_data: dict[int, list] = {}
    if zone_data_file.exists():
        data_key = f"data{suffix}"
        expr = f'pfDB["zones"]["{data_key}"] or pfDB["zones"]["data"]'
        for zid, d in iter_lua_table_entries(zone_data_file, expr, PRE_CODE_TEMPLATE):
            zone_data[int(zid)] = d

    all_zone_ids = set(zone_names.keys()) | set(zone_data.keys())
    zone_rows = []
    for zid in sorted(all_zone_ids):
        name = zone_names.get(zid)
        zd = zone_data.get(zid, [])
        map_id = zd[0] if len(zd) > 0 else None
        x_min = zd[1] if len(zd) > 1 else None
        y_min = zd[2] if len(zd) > 2 else None
        x_max = zd[3] if len(zd) > 3 else None
        y_max = zd[4] if len(zd) > 4 else None
        zone_rows.append((zid, name, map_id, x_min, x_max, y_min, y_max))

    conn.executemany(
        """
        INSERT INTO zones (id, name, map_id, x_min, x_max, y_min, y_max)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = COALESCE(excluded.name, zones.name),
            map_id = COALESCE(excluded.map_id, zones.map_id),
            x_min = COALESCE(excluded.x_min, zones.x_min),
            x_max = COALESCE(excluded.x_max, zones.x_max),
            y_min = COALESCE(excluded.y_min, zones.y_min),
            y_max = COALESCE(excluded.y_max, zones.y_max)
        """,
        zone_rows,
    )
    stats["zones"] = len(zone_rows)

    # 2. Units (NPCs)
    unit_names: dict[int, str] = {}
    unit_loc_file = loc_dir / f"units{loc_suffix}.lua"
    if unit_loc_file.exists():
        loc_key = f"{locale}{loc_suffix}"
        expr = f'pfDB["units"]["{loc_key}"] or pfDB["units"]["{locale}"]'
        for uid, name in iter_lua_table_entries(unit_loc_file, expr, PRE_CODE_TEMPLATE):
            unit_names[int(uid)] = str(name)

    unit_data_file = data_dir / f"units{suffix}.lua"
    unit_rows = []
    spawn_rows = []
    if unit_data_file.exists():
        data_key = f"data{suffix}"
        expr = f'pfDB["units"]["{data_key}"] or pfDB["units"]["data"]'
        for uid, udata in iter_lua_table_entries(unit_data_file, expr, PRE_CODE_TEMPLATE):
            uid_int = int(uid)
            name = unit_names.get(uid_int)
            min_l, max_l = _parse_level_range(udata.get("lvl") if isinstance(udata, dict) else None)
            rank = udata.get("rnk", 0) if isinstance(udata, dict) else 0
            fac = udata.get("fac") if isinstance(udata, dict) else None
            unit_rows.append((uid_int, name, min_l, max_l, rank, fac, None, 0))

            coords = udata.get("coords", []) if isinstance(udata, dict) else []
            coord_pts = list(coords.values()) if isinstance(coords, dict) else coords
            for pt in coord_pts:
                if isinstance(pt, list) and len(pt) >= 3:
                    x, y, zone_id = float(pt[0]), float(pt[1]), int(pt[2])
                    respawn = int(pt[3]) if len(pt) > 3 else 0
                    spawn_rows.append((uid_int, zone_id, x, y, respawn))

    # Add any units that only appear in loc file
    existing_unit_ids = {r[0] for r in unit_rows}
    for uid_int, name in unit_names.items():
        if uid_int not in existing_unit_ids:
            unit_rows.append((uid_int, name, None, None, 0, None, None, 0))

    conn.executemany(
        """
        INSERT INTO units (id, name, min_level, max_level, rank, faction, sub_name, npc_flags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = COALESCE(NULLIF(excluded.name, ''), units.name),
            min_level = COALESCE(excluded.min_level, units.min_level),
            max_level = COALESCE(excluded.max_level, units.max_level),
            rank = COALESCE(excluded.rank, units.rank),
            faction = COALESCE(excluded.faction, units.faction)
        """,
        unit_rows,
    )
    stats["units"] = len(unit_rows)

    # Make sure all zone IDs in spawn_rows exist in zones table to respect FK
    spawns_zone_ids = {r[1] for r in spawn_rows}
    missing_zones = spawns_zone_ids - all_zone_ids
    if missing_zones:
        conn.executemany(
            "INSERT OR IGNORE INTO zones (id, name) VALUES (?, ?)",
            [(zid, f"Zone {zid}") for zid in missing_zones],
        )

    conn.executemany(
        """
        INSERT OR IGNORE INTO unit_spawns (unit_id, zone_id, x, y, respawn_time)
        VALUES (?, ?, ?, ?, ?)
        """,
        spawn_rows,
    )
    stats["unit_spawns"] = len(spawn_rows)

    # 3. Objects
    obj_names: dict[int, str] = {}
    obj_loc_file = loc_dir / f"objects{loc_suffix}.lua"
    if obj_loc_file.exists():
        loc_key = f"{locale}{loc_suffix}"
        expr = f'pfDB["objects"]["{loc_key}"] or pfDB["objects"]["{locale}"]'
        for oid, name in iter_lua_table_entries(obj_loc_file, expr, PRE_CODE_TEMPLATE):
            obj_names[int(oid)] = str(name)

    obj_data_file = data_dir / f"objects{suffix}.lua"
    obj_rows = []
    obj_spawn_rows = []
    if obj_data_file.exists():
        data_key = f"data{suffix}"
        expr = f'pfDB["objects"]["{data_key}"] or pfDB["objects"]["data"]'
        for oid, odata in iter_lua_table_entries(obj_data_file, expr, PRE_CODE_TEMPLATE):
            oid_int = int(oid)
            name = obj_names.get(oid_int)
            fac = odata.get("fac") if isinstance(odata, dict) else None
            obj_rows.append((oid_int, name, fac, None))

            coords = odata.get("coords", []) if isinstance(odata, dict) else []
            coord_pts = list(coords.values()) if isinstance(coords, dict) else coords
            for pt in coord_pts:
                if isinstance(pt, list) and len(pt) >= 3:
                    x, y, zone_id = float(pt[0]), float(pt[1]), int(pt[2])
                    respawn = int(pt[3]) if len(pt) > 3 else 0
                    obj_spawn_rows.append((oid_int, zone_id, x, y, respawn))

    existing_obj_ids = {r[0] for r in obj_rows}
    for oid_int, name in obj_names.items():
        if oid_int not in existing_obj_ids:
            obj_rows.append((oid_int, name, None, None))

    conn.executemany(
        """
        INSERT INTO objects (id, name, faction, faction_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = COALESCE(NULLIF(excluded.name, ''), objects.name),
            faction = COALESCE(excluded.faction, objects.faction)
        """,
        obj_rows,
    )
    stats["objects"] = len(obj_rows)

    obj_spawns_zone_ids = {r[1] for r in obj_spawn_rows}
    missing_obj_zones = obj_spawns_zone_ids - all_zone_ids - missing_zones
    if missing_obj_zones:
        conn.executemany(
            "INSERT OR IGNORE INTO zones (id, name) VALUES (?, ?)",
            [(zid, f"Zone {zid}") for zid in missing_obj_zones],
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
    item_names: dict[int, str] = {}
    item_loc_file = loc_dir / f"items{loc_suffix}.lua"
    if item_loc_file.exists():
        loc_key = f"{locale}{loc_suffix}"
        expr = f'pfDB["items"]["{loc_key}"] or pfDB["items"]["{locale}"]'
        for iid, name in iter_lua_table_entries(item_loc_file, expr, PRE_CODE_TEMPLATE):
            item_names[int(iid)] = str(name)

    item_data_file = data_dir / f"items{suffix}.lua"
    item_rows = []
    drop_rows = []
    vendor_rows = []
    if item_data_file.exists():
        data_key = f"data{suffix}"
        expr = f'pfDB["items"]["{data_key}"] or pfDB["items"]["data"]'
        for iid, idata in iter_lua_table_entries(item_data_file, expr, PRE_CODE_TEMPLATE):
            iid_int = int(iid)
            name = item_names.get(iid_int)
            item_rows.append((iid_int, name, None, None, None, None, None, None, None, None))

            if isinstance(idata, dict):
                # Creature drops
                for uid, chance in (idata.get("U") or {}).items():
                    drop_rows.append((iid_int, "unit", int(uid), float(chance)))
                # Object drops
                for oid, chance in (idata.get("O") or {}).items():
                    drop_rows.append((iid_int, "object", int(oid), float(chance)))
                # Vendors
                for vid, stock in (idata.get("V") or {}).items():
                    vendor_rows.append((iid_int, int(vid), int(stock)))

    existing_item_ids = {r[0] for r in item_rows}
    for iid_int, name in item_names.items():
        if iid_int not in existing_item_ids:
            item_rows.append((iid_int, name, None, None, None, None, None, None, None, None))

    conn.executemany(
        """
        INSERT INTO items (id, name, item_level, required_level, class_id, subclass_id, food_type, ammo_type, flags, teaches_spell)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = COALESCE(NULLIF(excluded.name, ''), items.name)
        """,
        item_rows,
    )
    stats["items"] = len(item_rows)

    # Ensure foreign keys for vendor units exist
    vendor_uids = {r[1] for r in vendor_rows}
    missing_uids = vendor_uids - {r[0] for r in unit_rows}
    if missing_uids:
        conn.executemany(
            "INSERT OR IGNORE INTO units (id, name) VALUES (?, ?)",
            [(uid, f"Unknown Unit {uid}") for uid in missing_uids],
        )
        stats["units"] += len(missing_uids)

    conn.executemany(
        """
        INSERT OR IGNORE INTO item_drops (item_id, source_type, source_id, drop_chance)
        VALUES (?, ?, ?, ?)
        """,
        drop_rows,
    )
    stats["item_drops"] = len(drop_rows)

    conn.executemany(
        """
        INSERT OR IGNORE INTO item_vendors (item_id, unit_id, stock)
        VALUES (?, ?, ?)
        """,
        vendor_rows,
    )
    stats["item_vendors"] = len(vendor_rows)

    # 5. Quests
    quest_locs: dict[int, dict] = {}
    quest_loc_file = loc_dir / f"quests{loc_suffix}.lua"
    if quest_loc_file.exists():
        loc_key = f"{locale}{loc_suffix}"
        expr = f'pfDB["quests"]["{loc_key}"] or pfDB["quests"]["{locale}"]'
        for qid, qloc in iter_lua_table_entries(quest_loc_file, expr, PRE_CODE_TEMPLATE):
            if isinstance(qloc, dict):
                quest_locs[int(qid)] = qloc

    quest_data_file = data_dir / f"quests{suffix}.lua"
    quest_rows = []
    starter_rows = []
    finisher_rows = []
    objective_rows = []
    prereq_rows = []
    exclusive_rows = []

    if quest_data_file.exists():
        data_key = f"data{suffix}"
        expr = f'pfDB["quests"]["{data_key}"] or pfDB["quests"]["data"]'
        for qid, qdata in iter_lua_table_entries(quest_data_file, expr, PRE_CODE_TEMPLATE):
            qid_int = int(qid)
            qloc = quest_locs.get(qid_int, {})
            title = qloc.get("T")
            obj_text = qloc.get("O")
            desc = qloc.get("D")

            if not isinstance(qdata, dict):
                qdata = {}

            min_lvl = qdata.get("min")
            lvl = qdata.get("lvl")
            race = qdata.get("race")
            cls = qdata.get("class")
            next_q = qdata.get("next")
            if isinstance(next_q, list):
                next_q = int(next_q[0]) if next_q and isinstance(next_q[0], (int, float)) else None
            elif isinstance(next_q, (int, float)):
                next_q = int(next_q)
            else:
                next_q = None

            skill = qdata.get("skill")
            if isinstance(skill, (int, float)):
                skill = int(skill)
            elif isinstance(skill, list) and skill and isinstance(skill[0], (int, float)):
                skill = int(skill[0])
            else:
                skill = None

            skillmin = qdata.get("skillmin")
            if isinstance(skillmin, (int, float)):
                skillmin = int(skillmin)
            elif isinstance(skillmin, list) and skillmin and isinstance(skillmin[0], (int, float)):
                skillmin = int(skillmin[0])
            else:
                skillmin = None

            event = qdata.get("event")
            if isinstance(event, (int, float)):
                event = int(event)
            elif isinstance(event, list) and event and isinstance(event[0], (int, float)):
                event = int(event[0])
            else:
                event = None

            quest_rows.append(
                (
                    qid_int,
                    title,
                    min_lvl,
                    lvl,
                    race,
                    cls,
                    obj_text,
                    desc,
                    next_q,
                    skill,
                    skillmin,
                    None,
                    None,
                    None,
                    None,
                    event,
                    None,
                    None,
                    None,
                )
            )

            # Starters
            for uid in _as_list(qdata.get("start", {}).get("U")):
                starter_rows.append((qid_int, "unit", uid))
            for oid in _as_list(qdata.get("start", {}).get("O")):
                starter_rows.append((qid_int, "object", oid))
            for iid in _as_list(qdata.get("start", {}).get("I")):
                starter_rows.append((qid_int, "item", iid))

            # Finishers
            for uid in _as_list(qdata.get("end", {}).get("U")):
                finisher_rows.append((qid_int, "unit", uid))
            for oid in _as_list(qdata.get("end", {}).get("O")):
                finisher_rows.append((qid_int, "object", oid))

            # Objectives
            obj_data = qdata.get("obj") or {}
            for uid in _as_list(obj_data.get("U")):
                objective_rows.append((qid_int, "unit", uid, 0, None, None))
            for oid in _as_list(obj_data.get("O")):
                objective_rows.append((qid_int, "object", oid, 0, None, None))
            for iid in _as_list(obj_data.get("I")):
                objective_rows.append((qid_int, "item", iid, 0, None, None))
            for ir_id in _as_list(obj_data.get("IR")):
                objective_rows.append((qid_int, "itemreq", ir_id, 0, None, None))

            # Prerequisites
            for p in _as_list(qdata.get("pre")):
                prereq_rows.append((qid_int, p, 0))

            # Conflicting / Exclusive Quests
            for c in _as_list(qdata.get("close")):
                exclusive_rows.append((qid_int, c))

    # Any quests in loc file but missing from data file
    existing_quest_ids = {r[0] for r in quest_rows}
    for qid_int, qloc in quest_locs.items():
        if qid_int not in existing_quest_ids:
            quest_rows.append(
                (
                    qid_int,
                    qloc.get("T"),
                    None,
                    None,
                    None,
                    None,
                    qloc.get("O"),
                    qloc.get("D"),
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            )

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
            title = COALESCE(NULLIF(excluded.title, ''), quests.title),
            min_level = COALESCE(excluded.min_level, quests.min_level),
            quest_level = COALESCE(excluded.quest_level, quests.quest_level),
            required_races = COALESCE(excluded.required_races, quests.required_races),
            required_classes = COALESCE(excluded.required_classes, quests.required_classes),
            objective_text = COALESCE(NULLIF(excluded.objective_text, ''), quests.objective_text),
            description = COALESCE(NULLIF(excluded.description, ''), quests.description),
            next_quest_id = COALESCE(excluded.next_quest_id, quests.next_quest_id)
        """,
        quest_rows,
    )
    stats["quests"] = len(quest_rows)

    conn.executemany(
        """
        INSERT OR IGNORE INTO quest_starters (quest_id, starter_type, starter_id)
        VALUES (?, ?, ?)
        """,
        starter_rows,
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO quest_finishers (quest_id, finisher_type, finisher_id)
        VALUES (?, ?, ?)
        """,
        finisher_rows,
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO quest_objectives (quest_id, objective_type, target_id, amount, text, icon)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        objective_rows,
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO quest_prerequisites (quest_id, pre_quest_id, is_group)
        VALUES (?, ?, ?)
        """,
        prereq_rows,
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO quest_exclusive (quest_id, exclusive_quest_id)
        VALUES (?, ?)
        """,
        exclusive_rows,
    )

    # 6. Area Triggers
    at_file = data_dir / f"areatrigger{suffix}.lua"
    at_rows = []
    if at_file.exists():
        data_key = f"data{suffix}"
        expr = f'pfDB["areatrigger"]["{data_key}"] or pfDB["areatrigger"]["data"]'
        for at_id, at_data in iter_lua_table_entries(at_file, expr, PRE_CODE_TEMPLATE):
            coords = at_data.get("coords", []) if isinstance(at_data, dict) else []
            coord_pts = list(coords.values()) if isinstance(coords, dict) else coords
            for pt in coord_pts:
                if isinstance(pt, list) and len(pt) >= 3:
                    at_rows.append((int(at_id), None, int(pt[2]), float(pt[0]), float(pt[1])))
    if at_rows:
        at_zones = {r[2] for r in at_rows}
        missing_at_zones = at_zones - all_zone_ids - missing_zones - missing_obj_zones
        if missing_at_zones:
            conn.executemany(
                "INSERT OR IGNORE INTO zones (id, name) VALUES (?, ?)",
                [(zid, f"Zone {zid}") for zid in missing_at_zones],
            )
        conn.executemany(
            """
            INSERT OR REPLACE INTO areatriggers (id, name, zone_id, x, y)
            VALUES (?, ?, ?, ?, ?)
            """,
            at_rows,
        )
        stats["areatriggers"] = len(at_rows)

    # 7. Meta relations
    meta_file = data_dir / f"meta{suffix}.lua"
    meta_rows = []
    if meta_file.exists():
        meta_key = f"meta{suffix}"
        expr = f'pfDB["{meta_key}"] or pfDB["meta"]'
        for category, cat_dict in iter_lua_table_entries(meta_file, expr, PRE_CODE_TEMPLATE):
            if isinstance(cat_dict, dict):
                for eid, val in cat_dict.items():
                    meta_rows.append((str(category), int(eid), str(val) if val is not None else None))
    if meta_rows:
        conn.executemany(
            "INSERT OR REPLACE INTO meta (category, entity_id, value) VALUES (?, ?, ?)",
            meta_rows,
        )
        stats["meta"] = len(meta_rows)

    # 8. Minimap
    mini_file = data_dir / f"minimap{suffix}.lua"
    mini_rows = []
    if mini_file.exists():
        mini_key = f"minimap{suffix}"
        expr = f'pfDB["{mini_key}"] or pfDB["minimap"]'
        for zid, scales in iter_lua_table_entries(mini_file, expr, PRE_CODE_TEMPLATE):
            if isinstance(scales, list) and len(scales) >= 2:
                mini_rows.append((int(zid), float(scales[0]), float(scales[1])))
    if mini_rows:
        conn.executemany(
            "INSERT OR REPLACE INTO minimap (zone_id, x_scale, y_scale) VALUES (?, ?, ?)",
            mini_rows,
        )
        stats["minimap"] = len(mini_rows)

    # 9. Professions
    prof_file = loc_dir / f"professions{loc_suffix}.lua"
    prof_rows = []
    if prof_file.exists():
        loc_key = f"{locale}{loc_suffix}"
        expr = f'pfDB["professions"]["{loc_key}"] or pfDB["professions"]["{locale}"]'
        for pid, name in iter_lua_table_entries(prof_file, expr, PRE_CODE_TEMPLATE):
            prof_rows.append((int(pid), str(name)))
    if prof_rows:
        conn.executemany(
            "INSERT OR REPLACE INTO professions (id, name) VALUES (?, ?)",
            prof_rows,
        )
        stats["professions"] = len(prof_rows)

    overwrites_file = base_path / "overwrites.lua"
    if overwrites_file.exists():
        apply_pfquest_overwrites(conn, overwrites_file)

    conn.execute("UPDATE quests SET title = 'Quest #' || id WHERE title IS NULL OR title = ''")
    conn.commit()

    # Update stats with actual table counts
    for tbl in ("quests", "units", "objects", "items"):
        stats[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]

    return stats
