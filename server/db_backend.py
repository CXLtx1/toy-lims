"""SQLite/PostgreSQL database boundary for toy-lims.

SQLite remains available for tests and local recovery. Production uses psycopg
through this small compatibility layer so existing business SQL can migrate
without coupling Flask views to a database driver.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from urllib.parse import quote_plus

try:
    import psycopg
except ImportError:  # SQLite tests can still import the application.
    psycopg = None


IDENTITY_TABLES = {
    "analytes", "instruments", "dilutions", "volume_presets", "methods",
    "templates", "preparation_combinations", "report_profiles", "result_order_templates",
    "samples", "special_methods",
    "preparations", "sample_analytes", "readings", "instrument_imports",
    "standard_client_submissions", "xrf_analyses", "xrf_values",
    "uq_analyses", "uq_channels", "terminals", "users", "audit_logs",
}

POSTGRES_TABLE_ORDER = (
    "analytes", "chemical_elements", "common_oxides", "instruments", "instr_analytes", "dilutions",
    "volume_presets", "methods", "templates", "preparation_combinations", "report_profiles",
    "result_order_templates",
    "special_methods", "users", "samples", "special_results",
    "preparations", "sample_analytes", "results", "readings",
    "instrument_imports", "standard_client_submissions",
    "standard_client_sessions", "standard_client_status", "xrf_analyses",
    "xrf_values", "uq_analyses", "uq_channels", "xrf_client_status",
    "terminals", "audit_logs", "report_overrides", "number_sequences",
)


def postgres_dsn(config):
    """Build a DSN from the deliberately simple app.py configuration."""
    user = quote_plus(str(config["user"]))
    password = quote_plus(str(config["password"]))
    host = config.get("host", "127.0.0.1")
    port = int(config.get("port", 5432))
    database = quote_plus(str(config.get("database", "toy_lims")))
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def is_postgres_database(database):
    return str(database).lower().startswith(("postgresql://", "postgres://"))


class CompatRow(Mapping):
    """A row supporting sqlite3.Row's mapping and positional access."""

    def __init__(self, columns, values):
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._indexes = {name: index for index, name in enumerate(self._columns)}

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._values[self._indexes[key]]

    def __iter__(self):
        return iter(self._columns)

    def __len__(self):
        return len(self._columns)

    def keys(self):
        return self._columns


class EmptyCursor:
    rowcount = 0
    lastrowid = None

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())


class PostgresCursor:
    def __init__(self, cursor, returned=()):
        self._cursor = cursor
        self._columns = tuple(column.name for column in (cursor.description or ()))
        self._returned = list(returned)
        self.rowcount = cursor.rowcount
        self.lastrowid = self._returned[0][0] if self._returned else None

    def _row(self, value):
        return None if value is None else CompatRow(self._columns, value)

    def fetchone(self):
        if self._returned:
            return self._row(self._returned.pop(0))
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        values = self._returned + list(self._cursor.fetchall())
        self._returned.clear()
        return [self._row(value) for value in values]

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row


def _replace_qmarks(sql):
    """Convert DB-API qmarks without touching quoted text or SQL comments."""
    output = []
    index = 0
    quote = None
    line_comment = False
    block_comment = False
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""
        if line_comment:
            output.append(char)
            if char == "\n":
                line_comment = False
        elif block_comment:
            output.append(char)
            if char == "*" and next_char == "/":
                output.append(next_char)
                index += 1
                block_comment = False
        elif quote:
            output.append(char)
            if char == quote:
                if next_char == quote:
                    output.append(next_char)
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"'}:
            quote = char
            output.append(char)
        elif char == "-" and next_char == "-":
            output.extend((char, next_char))
            index += 1
            line_comment = True
        elif char == "/" and next_char == "*":
            output.extend((char, next_char))
            index += 1
            block_comment = True
        elif char == "?":
            output.append("%s")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _postgres_sql(sql, *, many=False):
    statement = sql.strip().rstrip(";")
    statement = statement.replace(
        "strftime('%Y-%m-%d %H:%M:%f','now','localtime')",
        "to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.MS')",
    )
    statement = statement.replace(
        "datetime('now','localtime','-60 seconds')",
        "to_char(clock_timestamp() - interval '60 seconds', 'YYYY-MM-DD HH24:MI:SS')",
    )
    statement = statement.replace(
        "datetime('now','localtime')",
        "to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')",
    )
    statement = re.sub(r"\bdatetime\(([A-Za-z_][A-Za-z0-9_.]*)\)", r"\1",
                       statement, flags=re.IGNORECASE)
    statement = re.sub(r"\bgroup_concat\(([^,()]+),\s*('[^']*')\)",
                       r"string_agg(\1::text, \2)", statement, flags=re.IGNORECASE)
    ignored = bool(re.match(r"INSERT\s+OR\s+IGNORE\s+INTO\b", statement, re.IGNORECASE))
    if ignored:
        statement = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO",
                           statement, count=1, flags=re.IGNORECASE)
        statement += " ON CONFLICT DO NOTHING"
    statement = _replace_qmarks(statement)
    match = re.match(r"INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\b",
                     statement, re.IGNORECASE)
    if (not many and match and match.group(1).lower() in IDENTITY_TABLES and
            not re.search(r"\bRETURNING\b", statement, re.IGNORECASE)):
        statement += " RETURNING id"
    return statement


def _split_statements(script):
    statements = []
    current = []
    quote = None
    for char in script:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def postgres_schema(sqlite_schema):
    """Translate the canonical SQLite DDL and order FK dependencies."""
    tables = {}
    extras = []
    for statement in _split_statements(sqlite_schema):
        match = re.search(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)",
                          statement, re.IGNORECASE)
        if match:
            tables[match.group(1).lower()] = statement
        else:
            extras.append(statement)
    ordered = [tables[name] for name in POSTGRES_TABLE_ORDER if name in tables]
    ordered.extend(extras)
    script = ";\n".join(ordered) + ";"
    script = re.sub(
        r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
        "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        script, flags=re.IGNORECASE,
    )
    script = re.sub(r"\bREAL\b", "DOUBLE PRECISION", script, flags=re.IGNORECASE)
    script = script.replace(
        "DEFAULT (datetime('now','localtime'))",
        "DEFAULT to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS')",
    )
    return script


class PostgresConnection:
    is_postgres = True

    def __init__(self, dsn):
        if psycopg is None:
            raise RuntimeError("PostgreSQL 后端需要安装 psycopg[binary]")
        self.raw = psycopg.connect(dsn, connect_timeout=10)
        # 数据库服务器可能运行在 UTC（如容器默认时区）；业务时间统一按本地时区生成。
        self.raw.execute("SET TIME ZONE 'Asia/Shanghai'")

    def execute(self, sql, params=()):
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            if self.raw.info.transaction_status == psycopg.pq.TransactionStatus.IDLE:
                self.raw.execute("BEGIN")
            return EmptyCursor()
        statement = _postgres_sql(sql)
        cursor = self.raw.execute(statement, tuple(params))
        returned = cursor.fetchall() if re.search(r"\bRETURNING\b", statement, re.IGNORECASE) else ()
        return PostgresCursor(cursor, returned)

    def executemany(self, sql, params):
        statement = _postgres_sql(sql, many=True)
        cursor = self.raw.cursor()
        cursor.executemany(statement, list(params))
        return PostgresCursor(cursor)

    def executescript(self, script):
        for statement in _split_statements(script):
            self.raw.execute(statement)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def connect_database(database):
    if is_postgres_database(database):
        return PostgresConnection(database)
    connection = sqlite3.connect(database, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.create_function("safe_int", 1, lambda value: int(value) if str(value).isdigit() else None)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


DATABASE_ERRORS = ((sqlite3.DatabaseError,) +
                   ((psycopg.DatabaseError,) if psycopg is not None else ()))
INTEGRITY_ERRORS = ((sqlite3.IntegrityError,) +
                    ((psycopg.IntegrityError,) if psycopg is not None else ()))
