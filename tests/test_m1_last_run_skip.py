"""M1: optional skip of last_run update (used by main.py --test)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from modules.m1_watcher import fetch_and_filter_emails


class TestM1SkipLastRun(unittest.TestCase):
    @patch("modules.m1_watcher._update_last_run")
    @patch("modules.m1_watcher.gmail_client.get_unread_since", return_value=[])
    @patch("modules.m1_watcher._load_people_config", return_value={"people": []})
    def test_skip_last_run_when_env_set(
        self, _mock_people, _mock_gmail, mock_update_last_run
    ) -> None:
        with patch.dict(os.environ, {"CHRONA_SKIP_LAST_RUN_UPDATE": "true"}):
            fetch_and_filter_emails()
        mock_update_last_run.assert_not_called()

    @patch("modules.m1_watcher._update_last_run")
    @patch("modules.m1_watcher.gmail_client.get_unread_since", return_value=[])
    @patch("modules.m1_watcher._load_people_config", return_value={"people": []})
    def test_updates_last_run_when_env_not_set(
        self, _mock_people, _mock_gmail, mock_update_last_run
    ) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONA_SKIP_LAST_RUN_UPDATE", None)
            fetch_and_filter_emails()
        mock_update_last_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
