"""pfQuest Lua database exporter."""

import sqlite3
from pathlib import Path


def _lua_str(s: str) -> str:
    """Escape and format string for Lua."""
    s = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{s}"'


def _format_lua_val(val, indent: int = 1) -> str:
    pad = "  " * indent
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return _lua_str(val)
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, list):
        if not val:
            return "{}"
        # If simple flat array of numbers
        if all(isinstance(x, (int, float)) for x in val) and len(val) <= 6:
            return "{ " + ", ".join(str(x) for x in val) + " }"
        parts = []
        for x in val:
            parts.append(f"{pad}  {_format_lua_val(x, indent + 1)},")
        return "{\n" + "\n".join(parts) + f"\n{pad}}}"
    if isinstance(val, dict):
        if not val:
            return "{}"
        parts = []
        for k in sorted(val.keys(), key=lambda x: (str(type(x)), x)):
            key_str = f"[{k}]" if isinstance(k, int) else f'["{k}"]'
            v_str = _format_lua_val(val[k], indent + 1)
            parts.append(f"{pad}  {key_str} = {v_str},")
        return "{\n" + "\n".join(parts) + f"\n{pad}}}"
    return "nil"


def export_pfquest(
    conn: sqlite3.Connection,
    output_dir: str | Path,
    flavor: str = "epoch",
    locale: str = "enUS",
) -> None:
    """
    Export SQLite tables to pfQuest Lua files in output_dir.
    flavor: 'epoch', 'wotlk', 'tbc', or '' (for default/classic).
    """
    out_path = Path(output_dir)
    data_dir = out_path / "db"
    loc_dir = data_dir / locale
    data_dir.mkdir(parents=True, exist_ok=True)
    loc_dir.mkdir(parents=True, exist_ok=True)

    suffix = f"-{flavor}" if flavor else ""
    data_key = f"data{suffix}"
    loc_key = f"{locale}{suffix}"

    # 1. Zones
    cur = conn.execute("SELECT id, name, map_id, x_min, y_min, x_max, y_max FROM zones ORDER BY id")
    zone_rows = cur.fetchall()

    with open(data_dir / f"zones{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["zones"]["{data_key}"] = {{\n')
        for r in zone_rows:
            zid, _, map_id, x_min, y_min, x_max, y_max = r
            if map_id is not None:
                coords = [map_id, x_min or 0.0, y_min or 0.0, x_max or 0.0, y_max or 0.0]
                coord_str = ", ".join(str(c) for c in coords)
                f.write(f"  [{zid}] = {{ {coord_str} }},\n")
        f.write("}\n")

    with open(loc_dir / f"zones{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["zones"]["{loc_key}"] = {{\n')
        for r in zone_rows:
            zid, name, *_ = r
            if name:
                f.write(f"  [{zid}] = {_lua_str(name)},\n")
        f.write("}\n")

    # 2. Units
    cur = conn.execute("SELECT id, name, min_level, max_level, rank, faction FROM units ORDER BY id")
    unit_rows = cur.fetchall()

    cur = conn.execute("SELECT unit_id, x, y, zone_id, respawn_time FROM unit_spawns ORDER BY unit_id, id")
    unit_spawns: dict[int, list] = {}
    for r in cur.fetchall():
        uid, x, y, zid, respawn = r
        unit_spawns.setdefault(uid, []).append([round(x, 2), round(y, 2), zid, respawn])

    with open(data_dir / f"units{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["units"]["{data_key}"] = {{\n')
        for r in unit_rows:
            uid, _, min_l, max_l, rank, fac = r
            spawns = unit_spawns.get(uid, [])
            if not spawns and not fac and min_l is None and not rank:
                continue
            f.write(f"  [{uid}] = {{\n")
            if spawns:
                f.write("    [\"coords\"] = {\n")
                for i, pt in enumerate(spawns, 1):
                    f.write(f"      [{i}] = {{ {pt[0]}, {pt[1]}, {pt[2]}, {pt[3]} }},\n")
                f.write("    },\n")
            if fac:
                f.write(f"    [\"fac\"] = {_lua_str(fac)},\n")
            if min_l is not None:
                lvl_str = f'"{min_l}"' if min_l == max_l else f'"{min_l}-{max_l}"'
                f.write(f"    [\"lvl\"] = {lvl_str},\n")
            if rank:
                f.write(f"    [\"rnk\"] = {rank},\n")
            f.write("  },\n")
        f.write("}\n")

    with open(loc_dir / f"units{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["units"]["{loc_key}"] = {{\n')
        for r in unit_rows:
            uid, name, *_ = r
            if name:
                f.write(f"  [{uid}] = {_lua_str(name)},\n")
        f.write("}\n")

    # 3. Objects
    cur = conn.execute("SELECT id, name, faction FROM objects ORDER BY id")
    obj_rows = cur.fetchall()

    cur = conn.execute("SELECT object_id, x, y, zone_id, respawn_time FROM object_spawns ORDER BY object_id, id")
    obj_spawns: dict[int, list] = {}
    for r in cur.fetchall():
        oid, x, y, zid, respawn = r
        obj_spawns.setdefault(oid, []).append([round(x, 2), round(y, 2), zid, respawn])

    with open(data_dir / f"objects{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["objects"]["{data_key}"] = {{\n')
        for r in obj_rows:
            oid, name, fac = r
            spawns = obj_spawns.get(oid, [])
            if not spawns and not fac:
                if name is None:
                    f.write(f"  [{oid}] = {{}},\n")
                continue
            f.write(f"  [{oid}] = {{\n")
            if spawns:
                f.write("    [\"coords\"] = {\n")
                for i, pt in enumerate(spawns, 1):
                    f.write(f"      [{i}] = {{ {pt[0]}, {pt[1]}, {pt[2]}, {pt[3]} }},\n")
                f.write("    },\n")
            if fac:
                f.write(f"    [\"fac\"] = {_lua_str(fac)},\n")
            f.write("  },\n")
        f.write("}\n")

    with open(loc_dir / f"objects{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["objects"]["{loc_key}"] = {{\n')
        for r in obj_rows:
            oid, name, _ = r
            if name is not None:
                f.write(f"  [{oid}] = {_lua_str(name)},\n")
        f.write("}\n")

    # 4. Items
    cur = conn.execute("SELECT id, name FROM items ORDER BY id")
    item_rows = cur.fetchall()

    cur = conn.execute("SELECT item_id, source_type, source_id, drop_chance FROM item_drops ORDER BY item_id")
    unit_drops: dict[int, dict[int, float]] = {}
    obj_drops: dict[int, dict[int, float]] = {}
    for r in cur.fetchall():
        iid, stype, sid, chance = r
        if stype == "unit":
            unit_drops.setdefault(iid, {})[sid] = round(chance, 4)
        elif stype == "object":
            obj_drops.setdefault(iid, {})[sid] = round(chance, 4)

    cur = conn.execute("SELECT item_id, unit_id, stock FROM item_vendors ORDER BY item_id")
    vendors: dict[int, dict[int, int]] = {}
    for r in cur.fetchall():
        iid, uid, stock = r
        vendors.setdefault(iid, {})[uid] = stock

    with open(data_dir / f"items{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["items"]["{data_key}"] = {{\n')
        for r in item_rows:
            iid, _ = r
            ud = unit_drops.get(iid, {})
            od = obj_drops.get(iid, {})
            vd = vendors.get(iid, {})
            if not ud and not od and not vd:
                continue
            f.write(f"  [{iid}] = {{\n")
            if ud:
                f.write("    [\"U\"] = {\n")
                for sid, chance in sorted(ud.items()):
                    f.write(f"      [{sid}] = {chance},\n")
                f.write("    },\n")
            if od:
                f.write("    [\"O\"] = {\n")
                for sid, chance in sorted(od.items()):
                    f.write(f"      [{sid}] = {chance},\n")
                f.write("    },\n")
            if vd:
                f.write("    [\"V\"] = {\n")
                for sid, stock in sorted(vd.items()):
                    f.write(f"      [{sid}] = {stock},\n")
                f.write("    },\n")
            f.write("  },\n")
        f.write("}\n")

    with open(loc_dir / f"items{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["items"]["{loc_key}"] = {{\n')
        for r in item_rows:
            iid, name = r
            if name:
                f.write(f"  [{iid}] = {_lua_str(name)},\n")
        f.write("}\n")

    # 5. Quests
    cur = conn.execute(
        """
        SELECT 
            id, title, min_level, quest_level, required_races, required_classes,
            objective_text, description, next_quest_id, required_skill_id,
            required_skill_value, event_id
        FROM quests 
        ORDER BY id
        """
    )
    quest_rows = cur.fetchall()

    # Pre-load starters, finishers, objectives, prereqs, exclusives
    starters: dict[int, dict[str, list[int]]] = {}
    cur = conn.execute("SELECT quest_id, starter_type, starter_id FROM quest_starters ORDER BY quest_id, id")
    for qid, stype, sid in cur.fetchall():
        key = "U" if stype == "unit" else ("O" if stype == "object" else "I")
        starters.setdefault(qid, {}).setdefault(key, []).append(sid)

    finishers: dict[int, dict[str, list[int]]] = {}
    cur = conn.execute("SELECT quest_id, finisher_type, finisher_id FROM quest_finishers ORDER BY quest_id, id")
    for qid, ftype, fid in cur.fetchall():
        key = "U" if ftype == "unit" else "O"
        finishers.setdefault(qid, {}).setdefault(key, []).append(fid)

    objectives: dict[int, dict[str, list[int]]] = {}
    cur = conn.execute("SELECT quest_id, objective_type, target_id FROM quest_objectives ORDER BY quest_id, id")
    for qid, otype, tid in cur.fetchall():
        if tid is not None:
            key = (
                "U"
                if otype == "unit"
                else (
                    "O"
                    if otype == "object"
                    else ("I" if otype == "item" else ("IR" if otype == "itemreq" else None))
                )
            )
            if key:
                objectives.setdefault(qid, {}).setdefault(key, []).append(tid)

    prereqs: dict[int, list[int]] = {}
    cur = conn.execute("SELECT quest_id, pre_quest_id FROM quest_prerequisites ORDER BY quest_id, id")
    for qid, pq in cur.fetchall():
        prereqs.setdefault(qid, []).append(pq)

    exclusives: dict[int, list[int]] = {}
    cur = conn.execute("SELECT quest_id, exclusive_quest_id FROM quest_exclusive ORDER BY quest_id, id")
    for qid, eq in cur.fetchall():
        exclusives.setdefault(qid, []).append(eq)

    with open(data_dir / f"quests{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["quests"]["{data_key}"] = {{\n')
        for r in quest_rows:
            (
                qid,
                _,
                min_lvl,
                lvl,
                races,
                classes,
                _,
                _,
                next_q,
                skill,
                skillmin,
                event,
            ) = r
            st = starters.get(qid, {})
            fin = finishers.get(qid, {})
            objs = objectives.get(qid, {})
            pre = prereqs.get(qid, [])
            close = exclusives.get(qid, [])

            f.write(f"  [{qid}] = {{\n")
            if st:
                f.write("    [\"start\"] = {\n")
                for k, ids in sorted(st.items()):
                    f.write(f"      [\"{k}\"] = {{ {', '.join(str(i) for i in ids)} }},\n")
                f.write("    },\n")
            if fin:
                f.write("    [\"end\"] = {\n")
                for k, ids in sorted(fin.items()):
                    f.write(f"      [\"{k}\"] = {{ {', '.join(str(i) for i in ids)} }},\n")
                f.write("    },\n")
            if objs:
                f.write("    [\"obj\"] = {\n")
                for k, ids in sorted(objs.items()):
                    f.write(f"      [\"{k}\"] = {{ {', '.join(str(i) for i in ids)} }},\n")
                f.write("    },\n")
            if close:
                f.write(f"    [\"close\"] = {{ {', '.join(str(i) for i in close)} }},\n")
            if pre:
                f.write(f"    [\"pre\"] = {{ {', '.join(str(i) for i in pre)} }},\n")
            if next_q:
                f.write(f"    [\"next\"] = {next_q},\n")
            if lvl is not None:
                f.write(f"    [\"lvl\"] = {lvl},\n")
            if min_lvl is not None:
                f.write(f"    [\"min\"] = {min_lvl},\n")
            if races:
                f.write(f"    [\"race\"] = {races},\n")
            if classes:
                f.write(f"    [\"class\"] = {classes},\n")
            if skill:
                f.write(f"    [\"skill\"] = {skill},\n")
            if skillmin:
                f.write(f"    [\"skillmin\"] = {skillmin},\n")
            if event:
                f.write(f"    [\"event\"] = {event},\n")
            f.write("  },\n")
        f.write("}\n")

    with open(loc_dir / f"quests{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["quests"]["{loc_key}"] = {{\n')
        for r in quest_rows:
            qid, title, _, _, _, _, obj_text, desc, *_ = r
            if title or obj_text or desc:
                f.write(f"  [{qid}] = {{\n")
                if title:
                    f.write(f"    [\"T\"] = {_lua_str(title)},\n")
                if obj_text:
                    f.write(f"    [\"O\"] = {_lua_str(obj_text)},\n")
                if desc:
                    f.write(f"    [\"D\"] = {_lua_str(desc)},\n")
                f.write("  },\n")
        f.write("}\n")

    # 6. Area Triggers
    cur = conn.execute("SELECT id, x, y, zone_id FROM areatriggers ORDER BY id")
    at_rows = cur.fetchall()
    if at_rows:
        with open(data_dir / f"areatrigger{suffix}.lua", "w", encoding="utf-8") as f:
            f.write(f'pfDB["areatrigger"]["{data_key}"] = {{\n')
            for aid, x, y, zid in at_rows:
                f.write(f"  [{aid}] = {{\n")
                f.write("    [\"coords\"] = {\n")
                f.write(f"      [1] = {{ {round(x, 2)}, {round(y, 2)}, {zid}, 0 }},\n")
                f.write("    },\n")
                f.write("  },\n")
            f.write("}\n")

    # 7. Meta relations
    cur = conn.execute("SELECT category, entity_id, value FROM meta ORDER BY category, entity_id")
    meta_dict: dict[str, dict[int, str]] = {}
    for cat, eid, val in cur.fetchall():
        meta_dict.setdefault(cat, {})[eid] = val or ""

    if meta_dict:
        meta_table = f"meta{suffix}"
        with open(data_dir / f"meta{suffix}.lua", "w", encoding="utf-8") as f:
            f.write(f'pfDB["{meta_table}"] = {{\n')
            for cat, entries in sorted(meta_dict.items()):
                f.write(f'  ["{cat}"] = {{\n')
                for eid, val in sorted(entries.items()):
                    val_out = f'"{val}"' if not val.isdigit() else val
                    f.write(f"    [{eid}] = {val_out},\n")
                f.write("  },\n")
            f.write("}\n")

    # 8. Minimap
    cur = conn.execute("SELECT zone_id, x_scale, y_scale FROM minimap ORDER BY zone_id")
    mini_rows = cur.fetchall()
    if mini_rows:
        mini_table = f"minimap{suffix}"
        with open(data_dir / f"minimap{suffix}.lua", "w", encoding="utf-8") as f:
            f.write(f'pfDB["{mini_table}"] = {{\n')
            for zid, xs, ys in mini_rows:
                f.write(f"  [{zid}] = {{ {xs}, {ys} }},\n")
            f.write("}\n")

    # 9. Professions
    cur = conn.execute("SELECT id, name FROM professions ORDER BY id")
    prof_rows = cur.fetchall()
    if prof_rows:
        with open(loc_dir / f"professions{suffix}.lua", "w", encoding="utf-8") as f:
            f.write(f'pfDB["professions"]["{loc_key}"] = {{\n')
            for pid, name in prof_rows:
                f.write(f"  [{pid}] = {_lua_str(name)},\n")
            f.write("}\n")
