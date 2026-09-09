"""Isolated PostgreSQL schemas for instrument-site tests."""

import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

SERVER_DIR = Path(__file__).resolve().parents[3] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from db_backend import connect_database  # noqa: E402


class CountingConnection:
    """Transparent wrapper that records execute() calls for SQL assertions."""

    def __init__(self, inner):
        self._inner = inner
        self.statements = []

    def execute(self, sql_text, params=None):
        self.statements.append(sql_text)
        return self._inner.execute(sql_text, params)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class PostgresCase(unittest.TestCase):
    def provision_database(self):
        base_dsn = os.environ.get("LIMS_TEST_DATABASE_URL", "").strip()
        if not base_dsn:
            self.skipTest("LIMS_TEST_DATABASE_URL is required for PostgreSQL integration tests")
        schema = f"test_{uuid4().hex}"
        admin = psycopg.connect(base_dsn, autocommit=True)
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        admin.close()

        def cleanup():
            connection = psycopg.connect(base_dsn, autocommit=True)
            try:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            finally:
                connection.close()

        self.addCleanup(cleanup)
        separator = "&" if "?" in base_dsn else "?"
        self.database = f"{base_dsn}{separator}options=-csearch_path%3D{schema}"

    def connect(self, counting=False):
        connection = connect_database(self.database)
        try:
            connection.commit()
            connection.autocommit = True
        except Exception:
            connection.close()
            raise
        return CountingConnection(connection) if counting else connection

    def run_script(self, script):
        connection = self.connect()
        try:
            for statement in (part.strip() for part in script.split(";")):
                if statement:
                    connection.execute(statement)
            connection.commit()
        finally:
            connection.close()
