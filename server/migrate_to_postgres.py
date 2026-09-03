"""One-time SQLite to PostgreSQL migration for the current laboratory data.

Reference/configuration data is copied in full. Sample business data is copied
only for the explicitly requested sample name (RY28888 by default).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import psycopg
from psycopg import sql

import app as lims
from db_backend import IDENTITY_TABLES, connect_database, postgres_dsn
from maintenance import create_backup


FULL_TABLES = (
    "users", "terminals", "analytes", "instruments", "dilutions",
    "volume_presets", "methods", "special_methods", "report_profiles", "result_order_templates",
    "templates", "preparation_combinations", "number_sequences", "instr_analytes",
)

SAMPLE_TABLES = (
    "samples", "sample_tags", "preparations", "special_results", "sample_analytes",
    "results", "readings", "instrument_imports", "xrf_analyses",
    "xrf_values", "uq_analyses", "uq_channels", "report_overrides",
    "standard_client_submissions", "audit_logs",
)

INSERT_ORDER = FULL_TABLES + SAMPLE_TABLES
TRUNCATE_TABLES = tuple(reversed(INSERT_ORDER)) + (
    "standard_client_sessions", "standard_client_status", "xrf_client_status",
)


def ensure_target_database(config):
    admin = dict(config)
    target_name = str(admin["database"])
    admin["database"] = "postgres"
    connection = psycopg.connect(postgres_dsn(admin), autocommit=True, connect_timeout=10)
    try:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", (target_name,)).fetchone()
        if not exists:
            connection.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(
                sql.Identifier(target_name)))
    finally:
        connection.close()


def table_rows(source, table):
    if not source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return []
    return [dict(row) for row in source.execute(f'SELECT * FROM "{table}"').fetchall()]


def referenced_ids(value, key):
    found = set()
    if isinstance(value, dict):
        for item_key, item in value.items():
            if item_key == key:
                try:
                    found.add(int(item))
                except (TypeError, ValueError):
                    pass
            found.update(referenced_ids(item, key))
    elif isinstance(value, list):
        for item in value:
            found.update(referenced_ids(item, key))
    return found


def filtered_rows(source, sample_name):
    all_rows = {table: table_rows(source, table) for table in INSERT_ORDER}
    keep_samples = {row["id"] for row in all_rows["samples"] if row["name"] == sample_name}
    if not keep_samples:
        raise RuntimeError(f"SQLite 中找不到样品名 {sample_name!r}")
    if len(keep_samples) != 1:
        raise RuntimeError(f"样品名 {sample_name!r} 不是唯一记录")

    selected = {table: list(all_rows[table]) for table in FULL_TABLES}
    selected["samples"] = [row for row in all_rows["samples"] if row["id"] in keep_samples]
    selected["preparations"] = [row for row in all_rows["preparations"]
                                if row["sample_id"] in keep_samples]
    selected["special_results"] = [row for row in all_rows["special_results"]
                                   if row["sample_id"] in keep_samples]
    selected["sample_analytes"] = [row for row in all_rows["sample_analytes"]
                                   if row["sample_id"] in keep_samples]
    keep_tasks = {row["id"] for row in selected["sample_analytes"]}
    selected["results"] = [row for row in all_rows["results"]
                           if row["sample_analyte_id"] in keep_tasks]
    selected["readings"] = [row for row in all_rows["readings"]
                            if row["sample_analyte_id"] in keep_tasks]
    keep_readings = {row["id"] for row in selected["readings"]}
    selected["instrument_imports"] = [row for row in all_rows["instrument_imports"]
                                      if row["sample_id"] in keep_samples]
    selected["xrf_analyses"] = [row for row in all_rows["xrf_analyses"]
                                if row["sample_id"] in keep_samples]
    keep_xrf = {row["id"] for row in selected["xrf_analyses"]}
    selected["xrf_values"] = [row for row in all_rows["xrf_values"]
                              if row["analysis_id"] in keep_xrf]
    keep_xrf_values = {row["id"] for row in selected["xrf_values"]}
    selected["uq_analyses"] = [row for row in all_rows["uq_analyses"]
                               if row.get("sample_id") in keep_samples or
                               row.get("xrf_analysis_id") in keep_xrf]
    keep_uq = {row["id"] for row in selected["uq_analyses"]}
    selected["uq_channels"] = [row for row in all_rows["uq_channels"]
                               if row["uq_analysis_id"] in keep_uq]
    selected["report_overrides"] = [row for row in all_rows["report_overrides"]
                                    if row["sample_id"] in keep_samples]

    submissions = []
    for row in all_rows["standard_client_submissions"]:
        try:
            payload = json.loads(row.get("payload_json") or "{}")
            response = json.loads(row.get("response_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        task_ids = referenced_ids(payload, "task_id") | referenced_ids(response, "task_id")
        reading_ids = referenced_ids(response, "reading_id")
        if task_ids & keep_tasks or reading_ids & keep_readings:
            submissions.append(row)
    selected["standard_client_submissions"] = submissions
    keep_submission_keys = {row["submission_id"] for row in submissions}

    sample_entities = {
        "sample": {str(value) for value in keep_samples},
        "sample_analyte": {str(value) for value in keep_tasks},
        "reading": {str(value) for value in keep_readings},
        "xrf_value": {str(value) for value in keep_xrf_values},
        "uq_analysis": {str(value) for value in keep_uq},
        "standard_submission": {str(value) for value in keep_submission_keys},
    }
    selected["audit_logs"] = [
        row for row in all_rows["audit_logs"]
        if row["action"] != "heartbeat" and (
            row["entity_type"] not in sample_entities or
            str(row.get("entity_id") or "") in sample_entities[row["entity_type"]]
        )
    ]
    return selected


def target_columns(target, table):
    return [row[0] for row in target.execute("""SELECT column_name
        FROM information_schema.columns WHERE table_schema='public' AND table_name=?
        ORDER BY ordinal_position""", (table,)).fetchall()]


def insert_rows(target, table, rows):
    if not rows:
        return
    available = set(target_columns(target, table))
    columns = [column for column in rows[0] if column in available]
    placeholders = ",".join("?" for _ in columns)
    names = ",".join(f'"{column}"' for column in columns)
    target.executemany(
        f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
        [tuple(row.get(column) for column in columns) for row in rows],
    )


def reset_sequences(source, target):
    highwater = {row["name"]: int(row["seq"]) for row in source.execute(
        "SELECT name,seq FROM sqlite_sequence").fetchall()}
    for table in sorted(IDENTITY_TABLES):
        sequence = target.execute("SELECT pg_get_serial_sequence(?, 'id')", (table,)).fetchone()[0]
        if not sequence:
            continue
        maximum = target.execute(f'SELECT COALESCE(MAX(id),0) FROM "{table}"').fetchone()[0]
        value = max(int(maximum or 0), highwater.get(table, 0))
        if value:
            target.execute("SELECT setval(?::regclass, ?, true)", (sequence, value))
        else:
            target.execute("SELECT setval(?::regclass, 1, false)", (sequence,))


def migrate(source_path, sample_name, replace=False, dry_run=False):
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    try:
        integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = source.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError("SQLite 完整性检查未通过，已停止迁移")
        selected = filtered_rows(source, sample_name)
        print("迁移计划：")
        for table in INSERT_ORDER:
            print(f"  {table}: {len(selected[table])}")
        if dry_run:
            return

        backup = create_backup(source_path, lims.BASE_DIR / "backups", 30)
        print(f"SQLite 迁移前备份：{backup}")
        ensure_target_database(lims.POSTGRES_CONFIG)
        lims.init_db()
        target = connect_database(lims.DB)
        try:
            existing = target.execute("SELECT COUNT(*) FROM information_schema.tables "
                                      "WHERE table_schema='public'").fetchone()[0]
            sample_count = target.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            if existing and sample_count and not replace:
                raise RuntimeError("PostgreSQL 已有样品数据；确认覆盖时使用 --replace")
            target.execute("TRUNCATE " + ",".join(f'"{table}"' for table in TRUNCATE_TABLES) +
                           " RESTART IDENTITY CASCADE")
            for table in INSERT_ORDER:
                insert_rows(target, table, selected[table])
            reset_sequences(source, target)
            target.commit()

            actual_samples = target.execute("SELECT id,name FROM samples ORDER BY id").fetchall()
            if len(actual_samples) != 1 or actual_samples[0]["name"] != sample_name:
                raise RuntimeError("PostgreSQL 样品核验失败")
            for table in FULL_TABLES:
                count = target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if count != len(selected[table]):
                    raise RuntimeError(f"PostgreSQL 表 {table} 行数核验失败")
            print(f"迁移完成：仅保留样品 {sample_name}（ID {actual_samples[0]['id']}）")
        except Exception:
            target.rollback()
            raise
        finally:
            target.close()
    finally:
        source.close()


def main():
    parser = argparse.ArgumentParser(description="迁移 toy-lims SQLite 到 PostgreSQL")
    parser.add_argument("--source", default=str(lims.BASE_DIR / "lims.db"))
    parser.add_argument("--sample", default="RY28888")
    parser.add_argument("--replace", action="store_true", help="清空目标 toy-lims 表后重建")
    parser.add_argument("--dry-run", action="store_true", help="只显示筛选后的行数")
    args = parser.parse_args()
    migrate(Path(args.source), args.sample, replace=args.replace, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
