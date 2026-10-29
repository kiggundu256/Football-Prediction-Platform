import unittest
from unittest.mock import Mock, patch
import requests
from api_football import ApiFootballError, fetch_fixtures


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

    @patch("api_football.requests.get", side_effect=requests.Timeout())
    def test_network_error_does_not_leak_request_details(self, get):
        with self.assertRaisesRegex(ApiFootballError, "Could not reach"):
            fetch_fixtures(api_key="test-key")


if __name__ == "__main__":
    unittest.main()
