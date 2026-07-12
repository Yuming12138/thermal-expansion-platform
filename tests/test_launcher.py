from __future__ import annotations

import unittest
from unittest.mock import patch

from te_platform.launcher import _browser_url, main


class LauncherTests(unittest.TestCase):
    def test_browser_url_uses_loopback_for_wildcard_host(self) -> None:
        self.assertEqual(_browser_url("0.0.0.0", 8123), "http://127.0.0.1:8123/")

    @patch("te_platform.launcher.uvicorn.run")
    def test_no_browser_starts_expected_app(self, run) -> None:
        self.assertEqual(main(["--no-browser", "--port", "8123"]), 0)
        run.assert_called_once_with(
            "te_platform.api.app:app",
            host="127.0.0.1",
            port=8123,
            log_level="info",
        )


if __name__ == "__main__":
    unittest.main()
