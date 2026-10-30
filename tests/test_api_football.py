import unittest
from unittest.mock import Mock, patch
import requests
from api_football import (ApiFootballError, fetch_fixtures, fetch_recent_team_fixtures, fetch_fixture_by_id, fetch_fixture_corner_statistics)


class ApiFootballTests(unittest.TestCase):
    @patch("api_football.requests.get")
    def test_fetches_fixture_list(self, get):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {"response": [{"fixture": {"id": 123}}], "errors": []}
        get.return_value = response
        result = fetch_fixtures(api_key="test-key", date="2026-10-29")
        self.assertEqual(result[0]["fixture"]["id"], 123)
        self.assertEqual(get.call_args.kwargs["headers"]["x-apisports-key"], "test-key")

    def test_requires_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ApiFootballError):
                fetch_fixtures(api_key=None)

    @patch("api_football.requests.get")
    def test_rejects_invalid_key(self, get):
        response = Mock()
        response.ok = False
        response.status_code = 401
        get.return_value = response
        with self.assertRaisesRegex(ApiFootballError, "rejected"):
            fetch_fixtures(api_key="bad-key")

    @patch("api_football.requests.get")
    def test_provider_error_details_are_preserved(self, get):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {"response": [], "errors": {"plan": "Access denied for this endpoint"}}
        get.return_value = response
        with self.assertRaisesRegex(ApiFootballError, "Access denied for this endpoint"):
            fetch_recent_team_fixtures(10, api_key="test-key", last=5, season=2026)

    @patch("api_football.requests.get", side_effect=requests.Timeout())
    def test_network_error_does_not_leak_request_details(self, get):
        with self.assertRaisesRegex(ApiFootballError, "Could not reach"):
            fetch_fixtures(api_key="test-key")


    @patch("api_football.requests.get")
    def test_fetches_recent_team_fixtures_without_last_parameter(self, get):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {"response": [
            {"fixture": {"id": 123, "date": "2024-10-20T18:00:00+00:00", "status": {"short": "FT"}}},
            {"fixture": {"id": 124, "date": "2024-10-25T18:00:00+00:00", "status": {"short": "NS"}}},
            {"fixture": {"id": 122, "date": "2024-10-18T18:00:00+00:00", "status": {"short": "FT"}}},
        ], "errors": []}
        get.return_value = response
        result = fetch_recent_team_fixtures(10, api_key="test-key", last=5, before_date="2026-10-30", season=2026)
        self.assertEqual([m["fixture"]["id"] for m in result], [123, 122])
        self.assertGreaterEqual(get.call_count, 1)
        params = get.call_args_list[0].kwargs["params"]
        self.assertEqual(params["team"], 10)
        self.assertEqual(params["season"], 2024)
        self.assertNotIn("from", params)
        self.assertNotIn("to", params)
        self.assertNotIn("last", params)

 
    @patch("api_football.requests.get")
    def test_fetches_fixture_by_id_for_settlement(self, get):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {"response": [{"fixture": {"id": 987}}], "errors": []}
        get.return_value = response
        result = fetch_fixture_by_id(987, api_key="test-key")
        self.assertEqual(result["fixture"]["id"], 987)
        self.assertEqual(get.call_args.kwargs["params"], {"id": 987})


    @patch("api_football.requests.get")
    def test_fetches_corner_statistics_by_team(self, get):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {"response": [
            {"team": {"id": 10}, "statistics": [{"type": "Corner Kicks", "value": 7}]},
            {"team": {"id": 20}, "statistics": [{"type": "Corner Kicks", "value": None}]},
        ], "errors": []}
        get.return_value = response
        result = fetch_fixture_corner_statistics(123, api_key="test-key")
        self.assertEqual(result, {10: 7, 20: None})
        self.assertEqual(get.call_args.kwargs["params"], {"fixture": 123, "type": "Corner Kicks"})

    @patch("api_football.requests.get")
    def test_missing_corner_statistics_returns_empty_mapping(self, get):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {"response": [], "errors": []}
        get.return_value = response
        self.assertEqual(fetch_fixture_corner_statistics(123, api_key="test-key"), {})

if __name__ == "__main__":
    unittest.main()
