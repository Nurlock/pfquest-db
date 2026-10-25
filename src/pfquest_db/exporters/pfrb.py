"""pfQuest-Reborn high performance Lua database exporter."""

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


def export_pfrb(
    conn: sqlite3.Connection,
    output_dir: str | Path,
    flavor: str = "",
    locale: str = "enUS",
) -> None:
    """
    Export SQLite tables to pfQuest-Reborn high-performance Lua files in output_dir.
    flavor: '' (default/classic) or custom flavor suffix.
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

            parts = []
            if fac:
                parts.append(f'["fac"] = "{fac}"')
            if min_l is not None:
                lvl_str = f'"{min_l}"' if min_l == max_l else f'"{min_l}-{max_l}"'
                parts.append(f'["lvl"] = {lvl_str}')
            if rank:
                parts.append(f'["rnk"] = {rank}')
            if spawns:
                spawns_str = ";".join(f"{pt[0]},{pt[1]},{pt[2]},{pt[3]}" for pt in spawns)
                parts.append(f'["__c"] = "{spawns_str}"')

            f.write(f"  [{uid}] = {{ {', '.join(parts)} }},\n")
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
                continue

            parts = []
            if fac:
                parts.append(f'["fac"] = "{fac}"')
            if spawns:
                spawns_str = ";".join(f"{pt[0]},{pt[1]},{pt[2]},{pt[3]}" for pt in spawns)
                parts.append(f'["__c"] = "{spawns_str}"')

            f.write(f"  [{oid}] = {{ {', '.join(parts)} }},\n")
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

            parts = []
            if ud:
                u_str = ",".join(f"{sid}:{chance}" for sid, chance in sorted(ud.items()))
                parts.append(f'["__U"] = "{u_str}"')
            if od:
                o_str = ",".join(f"{sid}:{chance}" for sid, chance in sorted(od.items()))
                parts.append(f'["__O"] = "{o_str}"')
            if vd:
                v_str = ",".join(f"{sid}:{stock}" for sid, stock in sorted(vd.items()))
                parts.append(f'["__V"] = "{v_str}"')

            f.write(f"  [{iid}] = {{ {', '.join(parts)} }},\n")
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

            parts = []
            if lvl is not None:
                parts.append(f'["lvl"] = {lvl}')
            if min_lvl is not None:
                parts.append(f'["min"] = {min_lvl}')
            if races:
                parts.append(f'["race"] = {races}')
            if classes:
                parts.append(f'["class"] = {classes}')
            if skill:
                parts.append(f'["skill"] = {skill}')
            if skillmin:
                parts.append(f'["skillmin"] = {skillmin}')
            if event:
                parts.append(f'["event"] = {event}')
            if next_q:
                parts.append(f'["next"] = {next_q}')
            if st:
                s_str = ";".join(f"{k}:{','.join(str(i) for i in ids)}" for k, ids in sorted(st.items()))
                parts.append(f'["__s"] = "{s_str}"')
            if fin:
                e_str = ";".join(f"{k}:{','.join(str(i) for i in ids)}" for k, ids in sorted(fin.items()))
                parts.append(f'["__e"] = "{e_str}"')
            if objs:
                o_str = ";".join(f"{k}:{','.join(str(i) for i in ids)}" for k, ids in sorted(objs.items()))
                parts.append(f'["__o"] = "{o_str}"')
            if pre:
                p_str = ",".join(str(i) for i in pre)
                parts.append(f'["__p"] = "{p_str}"')
            if close:
                c_str = ",".join(str(i) for i in close)
                parts.append(f'["__c"] = "{c_str}"')

            f.write(f"  [{qid}] = {{ {', '.join(parts)} }},\n")
        f.write("}\n")

    with open(loc_dir / f"quests{suffix}.lua", "w", encoding="utf-8") as f:
        f.write(f'pfDB["quests"]["{loc_key}"] = {{\n')
        for r in quest_rows:
            qid, title, _, _, _, _, obj_text, desc, *_ = r
            if title or obj_text or desc:
                parts = []
                if title:
                    parts.append(f'["T"] = {_lua_str(title)}')
                if obj_text:
                    parts.append(f'["O"] = {_lua_str(obj_text)}')
                if desc:
                    parts.append(f'["D"] = {_lua_str(desc)}')
                f.write(f"  [{qid}] = {{ {', '.join(parts)} }},\n")
        f.write("}\n")

    # 6. Area Triggers
    cur = conn.execute("SELECT id, x, y, zone_id FROM areatriggers ORDER BY id")
    at_rows = cur.fetchall()
    if at_rows:
        with open(data_dir / f"areatrigger{suffix}.lua", "w", encoding="utf-8") as f:
            f.write(f'pfDB["areatrigger"]["{data_key}"] = {{\n')
            for aid, x, y, zid in at_rows:
                f.write(f'  [{aid}] = {{ ["__c"] = "{round(x, 2)},{round(y, 2)},{zid},0" }},\n')
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


FLAVOR_TITLES = {
    "vanilla": "Vanilla",
    "epoch": "Project Epoch",
    "tbc": "The Burning Crusade",
    "wotlk": "Wrath of the Lich King",
}


def export_pfrb_lod_module(
    conn: sqlite3.Connection,
    output_dir: str | Path,
    flavor: str,
    locale: str = "enUS",
) -> Path:
    """
    Export SQLite database as a standalone Load-on-Demand (LoD) addon module
    named 'pfQuest-Reborn-{flavor}'.
    """
    out_path = Path(output_dir)
    mod_name = f"pfQuest-Reborn-{flavor}"
    mod_dir = out_path / mod_name
    mod_dir.mkdir(parents=True, exist_ok=True)

    # 1. Export Lua database files with flavor="" so they directly populate pfDB["..."]["data"] and pfDB["..."]["enUS"]
    export_pfrb(conn, mod_dir, flavor="", locale=locale)

    # 2. Generate init/data.xml
    init_dir = mod_dir / "init"
    init_dir.mkdir(parents=True, exist_ok=True)

    data_includes = [
        r'  <Include file="..\db\items.lua" />',
        r'  <Include file="..\db\units.lua" />',
        r'  <Include file="..\db\objects.lua" />',
        r'  <Include file="..\db\quests.lua" />',
        r'  <Include file="..\db\zones.lua" />',
    ]
    if (mod_dir / "db" / "minimap.lua").exists():
        data_includes.append(r'  <Include file="..\db\minimap.lua" />')
    if (mod_dir / "db" / "areatrigger.lua").exists():
        data_includes.append(r'  <Include file="..\db\areatrigger.lua" />')
    if (mod_dir / "db" / "meta.lua").exists():
        data_includes.append(r'  <Include file="..\db\meta.lua" />')

    with open(init_dir / "data.xml", "w", encoding="utf-8") as f:
        f.write('<Ui xmlns="http://www.blizzard.com/wow/ui/">\n')
        for inc in data_includes:
            f.write(f"{inc}\n")
        f.write("</Ui>\n")

    # 3. Generate init/{locale}.xml
    loc_includes = [
        f'  <Include file="..\\db\\{locale}\\items.lua" />',
        f'  <Include file="..\\db\\{locale}\\units.lua" />',
        f'  <Include file="..\\db\\{locale}\\objects.lua" />',
        f'  <Include file="..\\db\\{locale}\\quests.lua" />',
        f'  <Include file="..\\db\\{locale}\\zones.lua" />',
    ]
    if (mod_dir / "db" / locale / "professions.lua").exists():
        loc_includes.append(f'  <Include file="..\\db\\{locale}\\professions.lua" />')

    with open(init_dir / f"{locale}.xml", "w", encoding="utf-8") as f:
        f.write('<Ui xmlns="http://www.blizzard.com/wow/ui/">\n')
        for inc in loc_includes:
            f.write(f"{inc}\n")
        f.write("</Ui>\n")

    # 4. Generate TOC
    title = FLAVOR_TITLES.get(flavor, flavor.capitalize())
    toc_content = f"""## Interface: 30300
## Title: |cff33ffccpf|cffffffffQuest|r |cFF888888[Reborn]|r - {title} Database
## Notes: Load-on-Demand database ({title}) for pfQuest-Reborn
## Author: Shagu, txtsd, Nurlock
## Version: 1.0.0
## Dependencies: pfQuest-Reborn
## LoadOnDemand: 1

init\\data.xml
init\\{locale}.xml
"""
    with open(mod_dir / f"{mod_name}.toc", "w", encoding="utf-8") as f:
        f.write(toc_content)

    return mod_dir


def export_all_lod_modules(
    ref_dir: str | Path,
    output_dir: str | Path,
    locale: str = "enUS",
) -> list[Path]:
    """
    Export all reference SQLite databases (vanilla, epoch, tbc, wotlk) in ref_dir
    as standalone LoD addon modules in output_dir.
    """
    ref_path = Path(ref_dir)
    exported = []
    for flavor in ("vanilla", "epoch", "tbc", "wotlk"):
        db_file = ref_path / f"{flavor}.db"
        if not db_file.exists():
            continue
        conn = sqlite3.connect(db_file)
        mod_dir = export_pfrb_lod_module(conn, output_dir, flavor, locale=locale)
        conn.close()
        exported.append(mod_dir)
    return exported

