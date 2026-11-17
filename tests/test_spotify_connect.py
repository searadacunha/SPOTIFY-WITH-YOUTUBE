"""Spotify Connect activation tests; no network and no physical Android TV."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from common import Track, load_config
from main import Bridge
from smarttube_adb import ManualOverride, SmartTube
from storage import Store


class SpotifyConnectActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "connect.sqlite3")
        self.addCleanup(self.store.close)
        self.cfg = {**load_config(), "spotify_connect_autostart": True}
        self.track = Track("2" * 22, "Papaoutai", ("Stromae",), 232, "Racine carrée")
        self.video = dict(id="A" * 11, title="Stromae - Papaoutai (Official Music Video)",
                          channel="Stromae", channel_is_verified=True,
                          duration=232, live_status=None, view_count=500,
                          details_checked=True)
        self.store.remember(self.track, self.cfg, self.video)
        self.source = Mock()
        self.source.name = "tv"
        self.source.current.return_value = self.track
        self.tv = Mock()
        armed = {"ok": False}

        def claim(_track_id):
            armed["ok"] = True

        def guard(*_args, **_kwargs):
            if not armed["ok"]:
                raise ManualOverride("Manual override active")
            return {"generation": "phone"}

        def send(video_id, *, track_id, generation):
            self.store.record_handled(track_id,
                                      (self.cfg["tv_target"], self.cfg["smarttube_package"]),
                                      video_id, "sent")
            return True

        self.tv.claim_for_connect.side_effect = claim
        self.tv.check_control.side_effect = guard
        self.tv.send.side_effect = send
        self.bridge = Bridge(self.cfg, self.source, self.tv, self.store)

    def test_phone_connect_new_track_arms_before_control_check(self):
        self.assertEqual(self.bridge.step(), "sent")
        self.tv.claim_for_connect.assert_called_once_with(self.track.id)
        self.tv.send.assert_called_once_with("A" * 11, track_id=self.track.id, generation="phone")

    def test_same_track_does_not_rearm_or_replay(self):
        self.assertEqual(self.bridge.step(), "sent")
        self.assertEqual(self.bridge.step(), "duplicate")
        self.tv.claim_for_connect.assert_called_once()
        self.tv.send.assert_called_once()

    def test_next_phone_selected_track_rearms(self):
        self.assertEqual(self.bridge.step(), "sent")
        other = Track("3" * 22, "Another Song", ("Stromae",), 200)
        self.store.remember(other, self.cfg, {**self.video, "id": "B" * 11,
                                                  "title": "Stromae - Another Song (Official Music Video)",
                                                  "duration": 200})
        self.source.current.return_value = other
        self.assertEqual(self.bridge.step(), "sent")
        self.assertEqual(self.tv.claim_for_connect.call_count, 2)
        self.assertEqual(self.tv.send.call_args.args[0], "B" * 11)

    def test_paused_tv_session_never_grants_new_control(self):
        self.source.current.return_value = None
        # No remote session means ownership remains disarmed, rather than idle.
        self.assertEqual(self.bridge.step(), "manual_override")
        self.tv.claim_for_connect.assert_not_called()
        self.tv.send.assert_not_called()

    def test_legacy_manual_only_mode_remains_available(self):
        self.cfg["spotify_connect_autostart"] = False
        self.assertEqual(self.bridge.step(), "manual_override")
        self.source.current.assert_not_called()
        self.tv.claim_for_connect.assert_not_called()

    def test_dry_run_never_grants_control(self):
        self.assertEqual(Bridge(self.cfg, self.source, self.tv, self.store, dry_run=True).step(), "dry_run")
        self.tv.claim_for_connect.assert_not_called()
        self.tv.check_control.assert_not_called()
        self.tv.send.assert_not_called()

    def test_track_changed_while_resolving_is_not_sent(self):
        other = Track("3" * 22, "Other", ("Stromae",), 200)
        self.source.current.side_effect = [self.track, other]
        self.assertEqual(self.bridge.step(), "stale")
        self.tv.send.assert_not_called()


class PendingConnectOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "connect.sqlite3")
        self.addCleanup(self.store.close)
        self.cfg = {**load_config(), "spotify_connect_autostart": True}
        self.tv = SmartTube(self.cfg, self.store)

    def claim(self):
        with patch.object(self.tv, "foreground_app", return_value="com.android.tv.launcher"):
            return self.tv.claim_for_connect("2" * 22)

    def test_pending_claim_allows_same_foreground_before_first_send(self):
        state = self.claim()
        with patch.object(self.tv, "foreground_app", return_value="com.android.tv.launcher"):
            self.assertEqual(self.tv.check_control()["generation"], state["generation"])
        self.assertFalse(self.store.get_state("tv_control")["manual_override"])

    def test_other_app_takes_focus_and_revokes_pending_claim(self):
        self.claim()
        with patch.object(self.tv, "foreground_app", return_value="com.netflix.ninja"):
            with self.assertRaises(ManualOverride):
                self.tv.check_control()
        self.assertTrue(self.store.get_state("tv_control")["manual_override"])

    def test_pending_claim_expires(self):
        self.claim()
        with patch.object(self.tv, "foreground_app", return_value="com.android.tv.launcher"), \
             patch("smarttube_adb.time.time", return_value=time.time() + self.cfg["matching_timeout_seconds"] + 70):
            with self.assertRaises(ManualOverride):
                self.tv.check_control()
        self.assertTrue(self.store.get_state("tv_control")["manual_override"])

    def test_unknown_focus_cannot_claim(self):
        with patch.object(self.tv, "foreground_app", return_value=None):
            with self.assertRaises(ManualOverride):
                self.tv.claim_for_connect("2" * 22)
        self.assertTrue(self.store.get_state("tv_control")["manual_override"])

    def test_invalid_track_id_rejected_before_adb(self):
        with patch.object(self.tv, "foreground_app") as foreground:
            with self.assertRaises(ValueError):
                self.tv.claim_for_connect("bad-id")
            foreground.assert_not_called()


if __name__ == "__main__":
    unittest.main()
