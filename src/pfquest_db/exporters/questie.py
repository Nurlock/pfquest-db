"""Questie Lua database exporter."""

import sqlite3
from pathlib import Path
from typing import Optional


def _lua_str(s: str) -> str:
    s = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{s}"'


def _serialize_compact(val) -> str:
    if val is None:
        return "nil"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return _lua_str(val)
    if isinstance(val, list):
        if not val:
            return "nil"
        return "{" + ",".join(_serialize_compact(x) for x in val) + "}"
    if isinstance(val, dict):
        if not val:
            return "nil"
        items = []
        for k, v in sorted(val.items(), key=lambda x: (str(type(x[0])), x[0])):
            k_str = f"[{k}]" if isinstance(k, int) else f'["{k}"]'
            items.append(f"{k_str}={_serialize_compact(v)}")
        return "{" + ",".join(items) + "}"
    return "nil"


def _clean_sparse_list(lst: Optional[list]) -> Optional[list]:
    if not lst or not any(lst):
        return None
    cleaned = [x if x else None for x in lst]
    while cleaned and cleaned[-1] is None:
        cleaned.pop()
    return cleaned if cleaned else None


def _trim_trailing_nils(arr: list) -> list:
    while arr and arr[-1] is None:
        arr.pop()
    return arr


def export_questie(
    conn: sqlite3.Connection,
    output_dir: str | Path,
    flavor: str = "wotlk",
) -> None:
    """Export SQLite tables to Questie database files in output_dir."""
    out_path = Path(output_dir)
    target_dir = out_path / "Wotlk" if flavor == "wotlk" else out_path
    target_dir.mkdir(parents=True, exist_ok=True)

    prefix = flavor if flavor else ""

    # 1. NPCs (Units)
    cur = conn.execute("SELECT id, name, min_level, max_level, rank, faction, sub_name, npc_flags FROM units ORDER BY id")
    unit_rows = cur.fetchall()

    cur = conn.execute("SELECT unit_id, zone_id, x, y FROM unit_spawns ORDER BY unit_id, id")
    spawns: dict[int, dict[int, list[list[float]]]] = {}
    for uid, zid, x, y in cur.fetchall():
        spawns.setdefault(uid, {}).setdefault(zid, []).append([round(x, 2), round(y, 2)])

    cur = conn.execute("SELECT quest_id, starter_id FROM quest_starters WHERE starter_type = 'unit' ORDER BY starter_id")
    quest_starts: dict[int, list[int]] = {}
    for qid, uid in cur.fetchall():
        quest_starts.setdefault(uid, []).append(qid)

    cur = conn.execute("SELECT quest_id, finisher_id FROM quest_finishers WHERE finisher_type = 'unit' ORDER BY finisher_id")
    quest_ends: dict[int, list[int]] = {}
    for qid, uid in cur.fetchall():
        quest_ends.setdefault(uid, []).append(qid)

    with open(target_dir / f"{prefix}NpcDB.lua", "w", encoding="utf-8") as f:
        f.write("---@type QuestieDB\nlocal QuestieDB = QuestieLoader:ImportModule(\"QuestieDB\");\n\n")
        f.write("QuestieDB.npcData = [[return {\n")
        for r in unit_rows:
            uid, name, min_l, max_l, rank, fac, sub_name, npc_flags = r
            unit_spawns = spawns.get(uid)
            q_starts = quest_starts.get(uid)
            q_ends = quest_ends.get(uid)

            # Questie NPC structure:
            # 1: name, 2: minLevelHealth, 3: maxLevelHealth, 4: minLevel, 5: maxLevel,
            # 6: rank, 7: spawns, 8: waypoints, 9: zoneID, 10: questStarts,
            # 11: questEnds, 12: factionID, 13: friendlyToFaction, 14: subName, 15: npcFlags
            fields = [
                name or f"Creature #{uid}",
                None,
                None,
                min_l,
                max_l,
                rank or 0,
                unit_spawns,
                None,
                None,
                q_starts,
                q_ends,
                None,
                fac,
                sub_name,
                npc_flags or 0,
            ]
            _trim_trailing_nils(fields)
            f.write(f"[{uid}] = {{{','.join(_serialize_compact(x) for x in fields)}}},\n")
        f.write("}]]\n")

    # 2. Objects
    cur = conn.execute("SELECT id, name, faction, faction_id FROM objects ORDER BY id")
    obj_rows = cur.fetchall()

    cur = conn.execute("SELECT object_id, zone_id, x, y FROM object_spawns ORDER BY object_id, id")
    obj_spawns: dict[int, dict[int, list[list[float]]]] = {}
    for oid, zid, x, y in cur.fetchall():
        obj_spawns.setdefault(oid, {}).setdefault(zid, []).append([round(x, 2), round(y, 2)])

    cur = conn.execute("SELECT quest_id, starter_id FROM quest_starters WHERE starter_type = 'object' ORDER BY starter_id")
    obj_starts: dict[int, list[int]] = {}
    for qid, oid in cur.fetchall():
        obj_starts.setdefault(oid, []).append(qid)

    cur = conn.execute("SELECT quest_id, finisher_id FROM quest_finishers WHERE finisher_type = 'object' ORDER BY finisher_id")
    obj_ends: dict[int, list[int]] = {}
    for qid, oid in cur.fetchall():
        obj_ends.setdefault(oid, []).append(qid)

    with open(target_dir / f"{prefix}ObjectDB.lua", "w", encoding="utf-8") as f:
        f.write("---@type QuestieDB\nlocal QuestieDB = QuestieLoader:ImportModule(\"QuestieDB\");\n\n")
        f.write("QuestieDB.objectData = [[return {\n")
        for r in obj_rows:
            oid, name, _, fac_id = r
            o_spawns = obj_spawns.get(oid)
            q_starts = obj_starts.get(oid)
            q_ends = obj_ends.get(oid)

            # Questie Object structure:
            # 1: name, 2: questStarts, 3: questEnds, 4: spawns, 5: zoneID, 6: factionID
            fields = [name or f"Object #{oid}", q_starts, q_ends, o_spawns, None, fac_id]
            _trim_trailing_nils(fields)
            f.write(f"[{oid}] = {{{','.join(_serialize_compact(x) for x in fields)}}},\n")
        f.write("}]]\n")

    # 3. Items
    cur = conn.execute(
        """
        SELECT id, name, item_level, required_level, class_id, subclass_id,
               food_type, ammo_type, flags, teaches_spell
        FROM items ORDER BY id
        """
    )
    item_rows = cur.fetchall()

    cur = conn.execute("SELECT item_id, source_type, source_id FROM item_drops ORDER BY item_id")
    npc_drops: dict[int, list[int]] = {}
    object_drops: dict[int, list[int]] = {}
    for iid, stype, sid in cur.fetchall():
        if stype == "unit":
            npc_drops.setdefault(iid, []).append(sid)
        elif stype == "object":
            object_drops.setdefault(iid, []).append(sid)

    cur = conn.execute("SELECT item_id, unit_id FROM item_vendors ORDER BY item_id")
    item_vendors: dict[int, list[int]] = {}
    for iid, uid in cur.fetchall():
        item_vendors.setdefault(iid, []).append(uid)

    cur = conn.execute("SELECT quest_id, starter_id FROM quest_starters WHERE starter_type = 'item' ORDER BY starter_id")
    item_starts: dict[int, int] = {}
    for qid, iid in cur.fetchall():
        item_starts[iid] = qid

    with open(target_dir / f"{prefix}ItemDB.lua", "w", encoding="utf-8") as f:
        f.write("---@type QuestieDB\nlocal QuestieDB = QuestieLoader:ImportModule(\"QuestieDB\");\n\n")
        f.write("QuestieDB.itemData = [[return {\n")
        for r in item_rows:
            iid, name, ilvl, req_lvl, cls_id, subcls_id, food, ammo, flags, spell = r
            n_drops = npc_drops.get(iid)
            o_drops = object_drops.get(iid)
            vendors = item_vendors.get(iid)
            start_q = item_starts.get(iid)

            # Questie Item structure:
            # 1: name, 2: npcDrops, 3: objectDrops, 4: itemDrops, 5: startQuest,
            # 6: questRewards, 7: flags, 8: foodType, 9: itemLevel, 10: requiredLevel,
            # 11: ammoType, 12: class, 13: subClass, 14: vendors, 15: relatedQuests, 16: teachesSpell
            fields = [
                name or f"Item #{iid}",
                n_drops,
                o_drops,
                None,
                start_q,
                None,
                flags,
                food,
                ilvl,
                req_lvl,
                ammo,
                cls_id,
                subcls_id,
                vendors,
                None,
                spell,
            ]
            _trim_trailing_nils(fields)
            f.write(f"[{iid}] = {{{','.join(_serialize_compact(x) for x in fields)}}},\n")
        f.write("}]]\n")

    # 4. Quests
    cur = conn.execute(
        """
        SELECT 
            id, title, min_level, quest_level, required_races, required_classes,
            objective_text, next_quest_id, required_skill_id, required_skill_value,
            required_min_rep_faction, required_min_rep_value,
            required_max_rep_faction, required_max_rep_value,
            source_item_id, special_flags, quest_flags
        FROM quests ORDER BY id
        """
    )
    quest_rows = cur.fetchall()

    # Pre-fetch starters
    cur = conn.execute("SELECT quest_id, starter_type, starter_id FROM quest_starters ORDER BY quest_id, id")
    starters: dict[int, list[list[int]]] = {}
    for qid, stype, sid in cur.fetchall():
        idx = 0 if stype == "unit" else (1 if stype == "object" else 2)
        s_entry = starters.setdefault(qid, [[], [], []])
        s_entry[idx].append(sid)

    # Pre-fetch finishers
    cur = conn.execute("SELECT quest_id, finisher_type, finisher_id FROM quest_finishers ORDER BY quest_id, id")
    finishers: dict[int, list[list[int]]] = {}
    for qid, ftype, fid in cur.fetchall():
        idx = 0 if ftype == "unit" else 1
        f_entry = finishers.setdefault(qid, [[], []])
        f_entry[idx].append(fid)

    # Pre-fetch objectives
    cur = conn.execute("SELECT quest_id, objective_type, target_id, text, icon FROM quest_objectives ORDER BY quest_id, id")
    objectives: dict[int, list[list]] = {}
    req_items: dict[int, list[int]] = {}
    for qid, otype, tid, txt, icn in cur.fetchall():
        if otype == "itemreq":
            if tid is not None:
                req_items.setdefault(qid, []).append(tid)
            continue
        idx = 0 if otype == "unit" else (1 if otype == "object" else 2)
        obj_entry = objectives.setdefault(qid, [[], [], []])
        if txt or icn:
            obj_entry[idx].append([tid, txt, icn])
        else:
            obj_entry[idx].append([tid])

    # Pre-fetch prereqs
    cur = conn.execute("SELECT quest_id, pre_quest_id, is_group FROM quest_prerequisites ORDER BY quest_id, id")
    pre_single: dict[int, list[int]] = {}
    pre_group: dict[int, list[int]] = {}
    for qid, pq, is_g in cur.fetchall():
        if is_g:
            pre_group.setdefault(qid, []).append(pq)
        else:
            pre_single.setdefault(qid, []).append(pq)

    # Pre-fetch exclusives
    cur = conn.execute("SELECT quest_id, exclusive_quest_id FROM quest_exclusive ORDER BY quest_id, id")
    exclusives: dict[int, list[int]] = {}
    for qid, eq in cur.fetchall():
        exclusives.setdefault(qid, []).append(eq)

    with open(target_dir / f"{prefix}QuestDB.lua", "w", encoding="utf-8") as f:
        f.write("---@type QuestieDB\nlocal QuestieDB = QuestieLoader:ImportModule(\"QuestieDB\");\n\n")
        f.write("QuestieDB.questData = [[return {\n")
        for r in quest_rows:
            (
                qid,
                title,
                min_l,
                qlvl,
                races,
                classes,
                obj_text,
                next_q,
                sk_id,
                sk_val,
                min_rep_f,
                min_rep_v,
                max_rep_f,
                max_rep_v,
                source_item,
                spflags,
                qflags,
            ) = r

            # Starters: {[1]=creatures, [2]=objects, [3]=items}
            st = _clean_sparse_list(starters.get(qid))

            # Finishers: {[1]=creatures, [2]=objects}
            fin = _clean_sparse_list(finishers.get(qid))

            # Objectives: {[1]=creatures, [2]=objects, [3]=items}
            objs = _clean_sparse_list(objectives.get(qid))

            # Skill
            req_skill = [sk_id, sk_val] if sk_id is not None and sk_val is not None else None
            req_min_rep = [min_rep_f, min_rep_v] if min_rep_f is not None and min_rep_v is not None else None
            req_max_rep = [max_rep_f, max_rep_v] if max_rep_f is not None and max_rep_v is not None else None

            fields = [
                title or f"Quest #{qid}",
                st,
                fin,
                min_l,
                qlvl,
                races,
                classes,
                [obj_text] if obj_text else None,
                None,
                objs,
                source_item,
                pre_group.get(qid),
                pre_single.get(qid),
                None,
                None,
                exclusives.get(qid),
                None,
                req_skill,
                req_min_rep,
                req_max_rep,
                req_items.get(qid),
                next_q,
                qflags,
                spflags,
            ]
            _trim_trailing_nils(fields)
            f.write(f"[{qid}] = {{{','.join(_serialize_compact(x) for x in fields)}}},\n")
        f.write("}]]\n")
