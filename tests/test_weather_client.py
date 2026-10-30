import unittest
from unittest.mock import Mock, patch

from weather_client import fetch_match_weather


class WeatherClientTests(unittest.TestCase):
    @patch("weather_client.requests.get")
    def test_selects_nearest_hour_for_known_venue_coordinates(self, get):
        response = Mock()
        response.json.return_value = {
            "hourly": {
                "time": ["2026-11-01T15:00", "2026-11-01T16:00"],
                "temperature_2m": [25.0, 24.0],
                "precipitation_probability": [20, 60],
                "wind_speed_10m": [8.0, 12.0],
                "weather_code": [1, 61],
            }
        }
        response.raise_for_status.return_value = None
        get.return_value = response
        result = fetch_match_weather(0.31, 32.58, "2026-11-01T16:10:00+00:00")
        self.assertEqual(result["temperature_c"], 24.0)
        self.assertEqual(result["precipitation_probability"], 60)

    def test_missing_or_invalid_coordinates_are_not_guessed(self):
        self.assertIsNone(fetch_match_weather(None, None, "2026-11-01T16:00:00+00:00"))
        self.assertIsNone(fetch_match_weather(999, 32, "bad-date"))


if __name__ == "__main__":
    unittest.main()
