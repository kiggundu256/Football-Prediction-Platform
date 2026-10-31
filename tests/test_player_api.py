import unittest
from unittest.mock import Mock, patch

from api_football import (
    fetch_team_injuries, fetch_player_sidelined, fetch_fixture_player_statistics,
    ApiFootballError,
)


class PlayerApiTests(unittest.TestCase):
    @patch("api_football.requests.get")
    def test_fetch_team_injuries(self, get):
        get.return_value = Mock(ok=True, status_code=200)
        get.return_value.json.return_value = {"response": [{"player": {"id": 5}}], "errors": []}
        result = fetch_team_injuries(10, 2025, api_key="test-key")
        self.assertEqual(result[0]["player"]["id"], 5)
        self.assertEqual(get.call_args.kwargs["params"], {"team": 10, "season": 2025})
        self.assertTrue(get.call_args.args[0].endswith("/injuries"))

    @patch("api_football.requests.get")
    def test_fetch_player_sidelined(self, get):
        get.return_value = Mock(ok=True, status_code=200)
        get.return_value.json.return_value = {"response": [{"type": "Hamstring"}], "errors": []}
        self.assertEqual(fetch_player_sidelined(5, api_key="test-key")[0]["type"], "Hamstring")
        self.assertEqual(get.call_args.kwargs["params"], {"player": 5})

    @patch("api_football.requests.get")
    def test_fetch_fixture_player_statistics(self, get):
        get.return_value = Mock(ok=True, status_code=200)
        get.return_value.json.return_value = {"response": [{"team": {"id": 10}}], "errors": []}
        self.assertEqual(fetch_fixture_player_statistics(123, api_key="test-key")[0]["team"]["id"], 10)
        self.assertEqual(get.call_args.kwargs["params"], {"fixture": 123})
        self.assertTrue(get.call_args.args[0].endswith("/fixtures/players"))

    @patch("api_football.requests.get")
    def test_quota_error_is_reported(self, get):
        get.return_value = Mock(ok=False, status_code=429)
        with self.assertRaisesRegex(ApiFootballError, "limit reached"):
            fetch_team_injuries(10, 2025, api_key="test-key")


if __name__ == "__main__":
    unittest.main()
