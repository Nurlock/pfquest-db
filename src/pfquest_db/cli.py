"""Command line interface for pfQuest DB."""

import argparse
import csv
import io
import json
import sqlite3
import sys
from pathlib import Path

from .database import get_connection, init_db, get_db_stats, rebuild_search_index
from .importers import import_pfquest, import_questie, import_pfrb
from .exporters import export_pfquest, export_questie, export_pfrb, export_pfrb_lod_module, export_all_lod_modules
from .schema import SCHEMA_SQL, FTS_SCHEMA_SQL


def _require_existing_db(db_path: str) -> None:
    if not Path(db_path).is_file():
        print(f"Error: Database file '{db_path}' not found.", file=sys.stderr)
        sys.exit(1)


def cmd_init(args) -> int:
    conn = init_db(args.db)
    conn.close()
    print(f"Initialized database successfully at: {args.db}")
    return 0


def cmd_import_pfquest(args) -> int:
    conn = init_db(args.db)
    if args.base_src:
        print(f"Importing base pfQuest data from: {args.base_src} with overlay from: {args.src} -> {args.db}")
    else:
        print(f"Importing pfQuest [{args.flavor or 'classic'}] data from: {args.src} -> {args.db}")
    stats = import_pfquest(
        args.src,
        conn,
        flavor=args.flavor,
        locale=args.locale,
        base_src=args.base_src,
    )
    conn.close()
    print("Import complete! Records imported/updated:")
    for table, count in stats.items():
        if count > 0:
            print(f"  - {table:15s}: {count:,}")
    return 0


def cmd_export_pfquest(args) -> int:
    _require_existing_db(args.db)
    conn = get_connection(args.db)
    print(f"Exporting pfQuest [{args.flavor or 'classic'}] data from: {args.db} -> {args.dest}")
    export_pfquest(conn, args.dest, flavor=args.flavor, locale=args.locale)
    conn.close()
    print(f"Export complete to: {args.dest}")
    return 0


def cmd_import_pfrb(args) -> int:
    conn = init_db(args.db)
    print(f"Importing pfQuest-Reborn [{args.flavor or 'classic'}] data from: {args.src} -> {args.db}")
    stats = import_pfrb(
        conn,
        args.src,
        flavor=args.flavor,
        locale=args.locale,
        base_src=args.base_src,
    )
    conn.close()
    print("Import complete! Records imported/updated:")
    for table, count in stats.items():
        if count > 0:
            print(f"  - {table:15s}: {count:,}")
    return 0


def cmd_export_pfrb(args) -> int:
    _require_existing_db(args.db)
    conn = get_connection(args.db)
    if getattr(args, "lod", False):
        flavor = args.flavor or "vanilla"
        print(f"Exporting pfQuest-Reborn LoD module [{flavor}] from: {args.db} -> {args.dest}")
        mod_dir = export_pfrb_lod_module(conn, args.dest, flavor=flavor, locale=args.locale)
        conn.close()
        print(f"LoD module export complete: {mod_dir}")
        return 0

    print(f"Exporting pfQuest-Reborn [{args.flavor or 'classic'}] data from: {args.db} -> {args.dest}")
    export_pfrb(conn, args.dest, flavor=args.flavor, locale=args.locale)
    conn.close()
    print(f"Export complete to: {args.dest}")
    return 0


def cmd_export_pfrb_all(args) -> int:
    ref_dir = Path(args.ref_dir)
    if not ref_dir.is_dir():
        print(f"Error: Reference directory '{args.ref_dir}' not found.", file=sys.stderr)
        return 1

    print(f"Exporting all pfQuest-Reborn LoD modules from {ref_dir} -> {args.dest} ...")
    exported = export_all_lod_modules(ref_dir, args.dest, locale=args.locale)
    print(f"Successfully exported {len(exported)} LoD modules:")
    for mod in exported:
        print(f"  - {mod.name} ({mod})")
    return 0


def cmd_import_questie(args) -> int:
    conn = init_db(args.db)
    print(f"Importing Questie [{args.flavor}] data from: {args.src} -> {args.db}")
    stats = import_questie(args.src, conn, flavor=args.flavor)
    conn.close()
    print("Import complete! Records imported/updated:")
    for table, count in stats.items():
        if count > 0:
            print(f"  - {table:15s}: {count:,}")
    return 0


def cmd_export_questie(args) -> int:
    _require_existing_db(args.db)
    conn = get_connection(args.db)
    print(f"Exporting Questie [{args.flavor}] data from: {args.db} -> {args.dest}")
    export_questie(conn, args.dest, flavor=args.flavor)
    conn.close()
    print(f"Export complete to: {args.dest}")
    return 0


def cmd_stats(args) -> int:
    _require_existing_db(args.db)
    conn = get_connection(args.db)
    stats = get_db_stats(conn)
    conn.close()
    print(f"Database statistics for: {args.db}")
    total = 0
    for table, count in stats.items():
        print(f"  {table:16s}: {count:>8,}")
        total += count
    print("-" * 28)
    print(f"  {'Total records':16s}: {total:>8,}")
    return 0


def cmd_query(args) -> int:
    _require_existing_db(args.db)
    conn = get_connection(args.db)
    try:
        cur = conn.execute(args.sql)
    except sqlite3.Error as e:
        print(f"SQL Error: {e}", file=sys.stderr)
        conn.close()
        return 1

    if cur.description is None:
        conn.commit()
        print(f"Query executed successfully ({cur.rowcount} row(s) affected).")
        conn.close()
        return 0

    rows = cur.fetchall()
    col_names = [d[0] for d in cur.description]
    fmt = getattr(args, "format", "table") or "table"

    if fmt == "json":
        data = [dict(zip(col_names, list(r))) for r in rows]
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(col_names)
        for r in rows:
            writer.writerow(list(r))
        print(out.getvalue(), end="")
    elif fmt == "markdown":
        if not rows:
            print("No results returned.")
        else:
            print("| " + " | ".join(col_names) + " |")
            print("| " + " | ".join("---" for _ in col_names) + " |")
            for r in rows:
                print("| " + " | ".join(str(val) if val is not None else "" for val in r) + " |")
    else:  # table
        if not rows:
            print("No results returned.")
        else:
            print(" | ".join(col_names))
            print("-+-".join("-" * len(c) for c in col_names))
            for r in rows:
                print(" | ".join(str(val) if val is not None else "NULL" for val in r))
            print(f"\n({len(rows)} row(s))")

    conn.close()
    return 0


def cmd_search(args) -> int:
    _require_existing_db(args.db)
    conn = get_connection(args.db)
    sql = """
        SELECT entity_type, entity_id, name, extra_text, rank
        FROM search_index
        WHERE search_index MATCH ?
    """
    params = [args.query]
    if args.type:
        sql += " AND entity_type = ?"
        params.append(args.type)
    sql += " ORDER BY rank LIMIT ?"
    params.append(args.limit)

    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
    except sqlite3.OperationalError as e:
        print(f"Search error: {e}. Try running 'pfquest-db rebuild-index --db {args.db}' first.", file=sys.stderr)
        conn.close()
        return 1

    fmt = getattr(args, "format", "table") or "table"
    col_names = ["type", "id", "name", "snippet"]
    formatted_rows = [
        [r[0], r[1], r[2], (r[3][:60] + "...") if len(r[3] or "") > 60 else (r[3] or "")]
        for r in rows
    ]

    if fmt == "json":
        data = [
            {"type": r[0], "id": r[1], "name": r[2], "details": r[3]}
            for r in rows
        ]
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif fmt == "markdown":
        if not formatted_rows:
            print("No matches found.")
        else:
            print("| " + " | ".join(col_names) + " |")
            print("| " + " | ".join("---" for _ in col_names) + " |")
            for r in formatted_rows:
                print("| " + " | ".join(str(val) for val in r) + " |")
    else:
        if not formatted_rows:
            print("No matches found.")
        else:
            print(f"{'Type':<8} {'ID':<8} {'Name':<35} Details")
            print("-" * 75)
            for r in formatted_rows:
                print(f"{r[0]:<8} {r[1]:<8} {str(r[2])[:34]:<35} {r[3]}")
            print(f"\n({len(rows)} result(s))")

    conn.close()
    return 0


def cmd_rebuild_index(args) -> int:
    _require_existing_db(args.db)
    conn = get_connection(args.db)
    print(f"Rebuilding FTS5 search index on: {args.db} ...")
    count = rebuild_search_index(conn)
    conn.close()
    print(f"Search index rebuild complete: {count:,} records indexed.")
    return 0


def cmd_schema(args) -> int:
    print(SCHEMA_SQL)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="pfquest-db",
        description="SQLite database manager and pfQuest / Questie importer and exporter.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize a new SQLite database with schema and views")
    p_init.add_argument("--db", required=True, help="Path to output .db file")
    p_init.set_defaults(func=cmd_init)

    # import-pfquest
    p_imp_pfq = subparsers.add_parser("import-pfquest", help="Import pfQuest Lua database into SQLite")
    p_imp_pfq.add_argument("--src", required=True, help="Path to pfQuest addon root directory")
    p_imp_pfq.add_argument("--base-src", default=None, help="Optional path to base pfQuest addon directory (e.g. pfQuest-Reforged) to merge before overlay")
    p_imp_pfq.add_argument("--db", required=True, help="Path to target SQLite database")
    p_imp_pfq.add_argument("--flavor", default="epoch", help="pfQuest flavor ('epoch', 'wotlk', 'tbc', or '' for classic)")
    p_imp_pfq.add_argument("--locale", default="enUS", help="Locale folder name (default: enUS)")
    p_imp_pfq.set_defaults(func=cmd_import_pfquest)

    # export-pfquest
    p_exp_pfq = subparsers.add_parser("export-pfquest", help="Export SQLite database to pfQuest Lua files")
    p_exp_pfq.add_argument("--db", required=True, help="Path to SQLite database")
    p_exp_pfq.add_argument("--dest", required=True, help="Path to output directory")
    p_exp_pfq.add_argument("--flavor", default="epoch", help="pfQuest flavor ('epoch', 'wotlk', 'tbc', or '' for classic)")
    p_exp_pfq.add_argument("--locale", default="enUS", help="Locale folder name (default: enUS)")
    p_exp_pfq.set_defaults(func=cmd_export_pfquest)

    # import-pfrb / import-pf-rb
    p_imp_pfrb = subparsers.add_parser("import-pfrb", aliases=["import-pf-rb"], help="Import pfQuest-Reborn Lua database into SQLite")
    p_imp_pfrb.add_argument("--src", required=True, help="Path to pfQuest-Reborn addon root directory")
    p_imp_pfrb.add_argument("--base-src", default=None, help="Optional path to base addon directory to merge before overlay")
    p_imp_pfrb.add_argument("--db", required=True, help="Path to target SQLite database")
    p_imp_pfrb.add_argument("--flavor", default="", help="Flavor suffix (default: '' for classic)")
    p_imp_pfrb.add_argument("--locale", default="enUS", help="Locale folder name (default: enUS)")
    p_imp_pfrb.set_defaults(func=cmd_import_pfrb)

    # export-pfrb / export-pf-rb
    p_exp_pfrb = subparsers.add_parser("export-pfrb", aliases=["export-pf-rb"], help="Export SQLite database to pfQuest-Reborn high-performance Lua files")
    p_exp_pfrb.add_argument("--db", required=True, help="Path to SQLite database")
    p_exp_pfrb.add_argument("--dest", required=True, help="Path to output directory")
    p_exp_pfrb.add_argument("--flavor", default="", help="Flavor suffix or module name (e.g. 'vanilla', 'epoch', 'tbc', 'wotlk')")
    p_exp_pfrb.add_argument("--locale", default="enUS", help="Locale folder name (default: enUS)")
    p_exp_pfrb.add_argument("--lod", action="store_true", help="Export as a standalone Load-on-Demand (LoD) addon module")
    p_exp_pfrb.set_defaults(func=cmd_export_pfrb)

    # export-pfrb-all / export-pf-rb-all
    p_exp_pfrb_all = subparsers.add_parser("export-pfrb-all", aliases=["export-pf-rb-all"], help="Export all reference SQLite DBs (vanilla, epoch, tbc, wotlk) as standalone LoD addon modules")
    p_exp_pfrb_all.add_argument("--ref-dir", default="ref", help="Path to directory containing reference .db files (default: 'ref')")
    p_exp_pfrb_all.add_argument("--dest", required=True, help="Path to destination directory (e.g. AddOns folder or repo root)")
    p_exp_pfrb_all.add_argument("--locale", default="enUS", help="Locale folder name (default: enUS)")
    p_exp_pfrb_all.set_defaults(func=cmd_export_pfrb_all)

    # import-questie
    p_imp_qst = subparsers.add_parser("import-questie", help="Import Questie Lua database into SQLite")
    p_imp_qst.add_argument("--src", required=True, help="Path to Questie Database folder")
    p_imp_qst.add_argument("--db", required=True, help="Path to target SQLite database")
    p_imp_qst.add_argument("--flavor", default="wotlk", help="Questie database flavor prefix (e.g. wotlk)")
    p_imp_qst.set_defaults(func=cmd_import_questie)

    # export-questie
    p_exp_qst = subparsers.add_parser("export-questie", help="Export SQLite database to Questie Lua files")
    p_exp_qst.add_argument("--db", required=True, help="Path to SQLite database")
    p_exp_qst.add_argument("--dest", required=True, help="Path to output directory")
    p_exp_qst.add_argument("--flavor", default="wotlk", help="Questie database flavor prefix (e.g. wotlk)")
    p_exp_qst.set_defaults(func=cmd_export_questie)

    # stats
    p_stats = subparsers.add_parser("stats", help="Display summary stats of records in database")
    p_stats.add_argument("--db", required=True, help="Path to SQLite database")
    p_stats.set_defaults(func=cmd_stats)

    # query
    p_query = subparsers.add_parser("query", help="Execute an SQL query against the database and display results")
    p_query.add_argument("--db", required=True, help="Path to SQLite database")
    p_query.add_argument("sql", help="SQL query to execute")
    p_query.add_argument("--format", choices=["table", "json", "csv", "markdown"], default="table", help="Output format (default: table)")
    p_query.set_defaults(func=cmd_query)

    # search
    p_search = subparsers.add_parser("search", help="Full-text search across quests, NPCs, items, and objects")
    p_search.add_argument("--db", required=True, help="Path to SQLite database")
    p_search.add_argument("query", help="Search keyword(s) or FTS5 expression")
    p_search.add_argument("--type", choices=["quest", "unit", "item", "object"], default=None, help="Filter by entity type")
    p_search.add_argument("--limit", type=int, default=25, help="Maximum number of results (default: 25)")
    p_search.add_argument("--format", choices=["table", "json", "markdown"], default="table", help="Output format (default: table)")
    p_search.set_defaults(func=cmd_search)

    # rebuild-index
    p_rebuild = subparsers.add_parser("rebuild-index", help="Rebuild the FTS5 full-text search index")
    p_rebuild.add_argument("--db", required=True, help="Path to SQLite database")
    p_rebuild.set_defaults(func=cmd_rebuild_index)

    # schema
    p_schema = subparsers.add_parser("dump-schema", help="Print the DDL schema SQL")
    p_schema.set_defaults(func=cmd_schema)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
