import unittest

from cloud.postgres_historical_database import PostgresHistoricalDatabase
from cloud.qt_compat import Signal


class PostgresAdapterUnitTests(unittest.TestCase):
    def test_team_name_normalization_matches_sqlite_adapter(self):
        self.assertEqual(
            PostgresHistoricalDatabase._team_name_key("AFC Wimbledon"),
            "afcwimbledon",
        )

    def test_payload_accepts_jsonb_mapping_and_json_text(self):
        mapping = {"fixture": {"id": 7}}
        self.assertIs(PostgresHistoricalDatabase._payload(mapping), mapping)
        self.assertEqual(
            PostgresHistoricalDatabase._payload('{"fixture":{"id":7}}'),
            mapping,
        )

    def test_provider_team_id_is_restored_on_imported_name_match(self):
        match = {
            "teams": {
                "home": {"name": "Alpha FC"},
                "away": {"name": "Beta FC"},
            }
        }
        updated = PostgresHistoricalDatabase._attach_provider_team_id(
            match, "Alpha FC", 123
        )
        self.assertEqual(updated["teams"]["home"]["id"], 123)
        self.assertNotIn("id", updated["teams"]["away"])


class HeadlessSignalTests(unittest.TestCase):
    def test_fallback_signal_delivers_payload_to_connected_callback(self):
        class Worker:
            completed = Signal(dict)
        worker = Worker()
        received = []
        worker.completed.connect(received.append)
        payload = {"predictions": 3}
        worker.completed.emit(payload)
        self.assertEqual(received, [payload])


if __name__ == "__main__":
    unittest.main()
