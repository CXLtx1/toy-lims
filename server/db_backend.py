"""PostgreSQL connection boundary for LabFlow."""

from collections.abc import Mapping

import psycopg


class Record(Mapping):
    """Database row with named access plus compact positional access."""

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


def record_row(cursor):
    columns = [column.name for column in (cursor.description or ())]
    return lambda values: Record(columns, values)


class DatabaseConnection:
    def __init__(self, dsn):
        if not str(dsn).lower().startswith(("postgresql://", "postgres://")):
            raise ValueError("LIMS_DATABASE_URL must be a PostgreSQL DSN")
        self.raw = psycopg.connect(dsn, connect_timeout=10, row_factory=record_row)
        self.raw.execute("SET TIME ZONE 'Asia/Shanghai'")
        self.raw.commit()

    @property
    def autocommit(self):
        return self.raw.autocommit

    @autocommit.setter
    def autocommit(self, value):
        self.raw.autocommit = value

    def execute(self, sql, params=None):
        return self.raw.execute(sql, tuple(params) if params else None)

    def executemany(self, sql, params):
        cursor = self.raw.cursor()
        cursor.executemany(sql, list(params))
        return cursor

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def connect_database(database):
    return DatabaseConnection(database)


DATABASE_ERRORS = (psycopg.DatabaseError,)
INTEGRITY_ERRORS = (psycopg.IntegrityError,)
