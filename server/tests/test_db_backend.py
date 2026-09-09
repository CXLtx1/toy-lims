import unittest
from unittest import mock

import db_backend
from db_backend import DatabaseConnection, Record, connect_database
from db_schema import SCHEMA, initialize_database
from postgres_case import PostgresTestCase


class DatabaseBackendTest(unittest.TestCase):
    def test_record_supports_mapping_and_position(self):
        row = Record(("id", "name"), (15, "RY28888"))
        self.assertEqual(15, row[0])
        self.assertEqual("RY28888", row["name"])
        self.assertEqual({"id": 15, "name": "RY28888"}, dict(row))
        self.assertEqual(2, len(row))
        self.assertEqual(("id", "name"), tuple(row.keys()))

    def test_connection_rejects_non_postgres_dsn(self):
        for dsn in ("sqlite:///lims.db", "mysql://x/y", "/path/to/db", "", None):
            with self.subTest(dsn=dsn):
                with self.assertRaises(ValueError):
                    connect_database(dsn)

    def test_postgres_connection_sets_local_time_zone(self):
        fake_raw = mock.MagicMock()
        with mock.patch.object(db_backend, "psycopg") as fake_psycopg:
            fake_psycopg.connect.return_value = fake_raw
            DatabaseConnection("postgresql://example")
        fake_psycopg.connect.assert_called_once_with(
            "postgresql://example", connect_timeout=10,
            row_factory=db_backend.record_row)
        fake_raw.execute.assert_called_once_with("SET TIME ZONE 'Asia/Shanghai'")
        fake_raw.commit.assert_called_once_with()

    def test_execute_without_parameters_keeps_percent_literals(self):
        fake_raw = mock.MagicMock()
        cursor = mock.MagicMock(description=None, rowcount=0)
        with mock.patch.object(db_backend, "psycopg") as fake_psycopg:
            fake_psycopg.connect.return_value = fake_raw
            fake_raw.execute.return_value = cursor
            connection = DatabaseConnection("postgresql://example")
            fake_raw.execute.reset_mock()
            connection.execute("ALTER TABLE methods ADD output_unit TEXT DEFAULT '%'")
        fake_raw.execute.assert_called_once_with(
            "ALTER TABLE methods ADD output_unit TEXT DEFAULT '%'", None)

    def test_schema_defines_core_tables(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS reading_create_requests(", SCHEMA)
        self.assertIn("client_reading_id TEXT PRIMARY KEY", SCHEMA)
        self.assertIn("CREATE TABLE IF NOT EXISTS chemical_elements", SCHEMA)
        self.assertIn("CREATE TABLE IF NOT EXISTS common_oxides", SCHEMA)


class PostgresSeedTest(PostgresTestCase):
    def setUp(self):
        self.provision_database()

    def test_chemical_element_reference_data_is_complete_and_idempotent(self):
        db = self.connect()
        try:
            self.assertEqual(87, db.execute("SELECT COUNT(*) FROM chemical_elements").fetchone()[0])
            self.assertEqual((26, "Fe", "铁", 55.845, 0), db.execute(
                "SELECT atomic_number,symbol,name_zh,atomic_weight,is_mass_number "
                "FROM chemical_elements WHERE symbol='Fe'").fetchone()[:])
            self.assertEqual({("Tc", 98.0), ("Pm", 145.0), ("Pu", 244.0), ("Am", 243.0)}, {
                row[:] for row in db.execute(
                    "SELECT symbol,atomic_weight FROM chemical_elements WHERE is_mass_number=1")})
            self.assertEqual(("Bi", "铋", 208.98), db.execute(
                "SELECT symbol,name_zh,atomic_weight FROM chemical_elements "
                "WHERE atomic_number=83").fetchone()[:])
            self.assertEqual(79, db.execute("SELECT COUNT(*) FROM common_oxides").fetchone()[0])
            ferric = db.execute("""SELECT name_zh,element_count,oxygen_count,
                molar_mass,element_mass_fraction,element_to_oxide_factor,is_conventional
                FROM common_oxides WHERE formula='Fe2O3'""").fetchone()
            self.assertEqual(("三氧化二铁", 2, 3), ferric[:3])
            self.assertAlmostEqual(159.687, ferric[3], places=6)
            self.assertAlmostEqual(1.4297340854, ferric[5], places=9)
            self.assertAlmostEqual(1.0, ferric[4] * ferric[5], places=12)
            self.assertEqual(1, ferric[6])
            self.assertEqual({"FeO", "Fe2O3", "Fe3O4"}, {row[0] for row in db.execute(
                "SELECT formula FROM common_oxides WHERE element_symbol='Fe'")})
            mercury = db.execute("""SELECT element_symbol,element_count,oxygen_count,
                element_to_oxide_factor,is_conventional FROM common_oxides
                WHERE formula='HgO'""").fetchone()
            self.assertEqual(("Hg", 1, 1), mercury[:3])
            self.assertAlmostEqual(1.0797597089, mercury[3], places=9)
            self.assertEqual(1, mercury[4])
            db.execute("UPDATE chemical_elements SET atomic_weight=999 WHERE symbol='Fe'")
            db.execute("UPDATE common_oxides SET element_to_oxide_factor=999 WHERE formula='Fe2O3'")
            db.commit()
        finally:
            db.close()
        initialize_database(self.database)
        db = self.connect()
        try:
            self.assertEqual(55.845, db.execute(
                "SELECT atomic_weight FROM chemical_elements WHERE symbol='Fe'").fetchone()[0])
            self.assertAlmostEqual(1.4297340854, db.execute(
                "SELECT element_to_oxide_factor FROM common_oxides "
                "WHERE formula='Fe2O3'").fetchone()[0], places=9)
        finally:
            db.close()

    def test_approved_formula_catalog_is_seeded_once(self):
        import app as lims
        db = self.connect()
        try:
            rows = db.execute("""SELECT name,formula,output_unit,active
                FROM methods WHERE itype='function' ORDER BY sort_order,id""").fetchall()
            self.assertEqual(27, len(rows))
            self.assertTrue(all(row["active"] == 1 for row in rows))
            self.assertEqual("Cu-碘量法", rows[0]["name"])
            self.assertEqual("TN-总氮浓度计算", rows[-1]["name"])
            self.assertEqual("ppm", next(row["output_unit"] for row in rows
                                         if row["name"] == "COD-重铬酸钾法"))
            self.assertEqual("mol/L", next(row["output_unit"] for row in rows
                                           if row["name"] == "H+-酸碱滴定法"))
            for row in rows:
                lims.formula_variables(row["formula"])
        finally:
            db.close()
        initialize_database(self.database)
        db = self.connect()
        try:
            self.assertEqual(27, db.execute(
                "SELECT COUNT(*) FROM methods WHERE itype='function'").fetchone()[0])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
