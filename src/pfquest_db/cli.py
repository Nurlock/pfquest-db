"""Command line interface for pfQuest DB."""

import argparse
import sys
from pathlib import Path

from .database import get_connection, init_db, get_db_stats
from .importers import import_pfquest, import_questie
from .exporters import export_pfquest, export_questie
from .schema import SCHEMA_SQL


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
    cur = conn.execute(args.sql)
    if cur.description is None:
        conn.commit()
        print(f"Query executed successfully ({cur.rowcount} row(s) affected).")
        conn.close()
        return 0

    rows = cur.fetchall()
    if not rows:
        print("No results returned.")
        conn.close()
        return 0

    col_names = [d[0] for d in cur.description]
    # Format as table
    print(" | ".join(col_names))
    print("-+-".join("-" * len(c) for c in col_names))
    for r in rows:
        print(" | ".join(str(val) if val is not None else "NULL" for val in r))
    print(f"\n({len(rows)} row(s))")
    conn.close()
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
    p_query.set_defaults(func=cmd_query)

    # schema
    p_schema = subparsers.add_parser("dump-schema", help="Print the DDL schema SQL")
    p_schema.set_defaults(func=cmd_schema)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
