import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api_usage import api_requests_today, record_api_request


class ApiUsageTests(unittest.TestCase):
    def test_counts_outgoing_requests_without_storing_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "usage.db"
            with patch("api_usage.usage_db_path", return_value=database):
                before = api_requests_today()
                record_api_request("fixtures")
                record_api_request("fixtures/statistics")
                self.assertEqual(api_requests_today(), before + 2)


if __name__ == "__main__":
    unittest.main()
