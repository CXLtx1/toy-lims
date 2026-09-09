"""Isolated PostgreSQL schemas for integration tests."""

import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql

from db_backend import connect_database
from db_schema import initialize_database


class PostgresTestCase(unittest.TestCase):
    def provision_database(self, app_module=None, *, initialize=True):
        base_dsn = os.environ.get("LIMS_TEST_DATABASE_URL", "").strip()
        if not base_dsn:
            self.skipTest("LIMS_TEST_DATABASE_URL is required for PostgreSQL integration tests")
        schema = f"test_{uuid4().hex}"
        admin = psycopg.connect(base_dsn, autocommit=True)
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        admin.close()
        separator = "&" if "?" in base_dsn else "?"
        self.database = f"{base_dsn}{separator}options=-csearch_path%3D{schema}"

        def cleanup():
            connection = psycopg.connect(base_dsn, autocommit=True)
            try:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            finally:
                connection.close()

        self.addCleanup(cleanup)
        if app_module is not None:
            config = patch.dict(app_module.app.config, {
                "LIMS_DATABASE_URL": self.database,
                "DATABASE_URL": None,
            })
            config.start()
            self.addCleanup(config.stop)
        if initialize:
            initialize_database(self.database)

    def connect(self):
        return connect_database(self.database)
