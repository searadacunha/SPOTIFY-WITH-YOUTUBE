"""Phone-originated Spotify Connect playback: all tests are offline."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from common import Track, load_config
from main import Bridge
from smarttube_adb import ManualOverride, SmartTube
from spotify_source import from_connect
from storage import Store


TRACK = {
    "is_playing": True,
    "currently_playing_type": "track",
    "device": {"id": "tv-device-id", "name": "Living Room", "is_active": True},
    "item": {"id": "0" * 22, "name": "Papaoutai",
             "artists": [{"name": "Stromae"}], "duration_ms": 232000,
             "album": {"name": "Racine carrée"}, "is_local": False},
}


class RemoteSourceTests(unittest.TestCase):
    def test_accepts_only_exact_target_device(self):
        track = from_connect(TRACK, "tv-device-id")
        self.assertEqual(track.title, "Papaoutai")
        self.assertEqual(track.id, "0" * 22)
        self.assertIsNone(from_connect(TRACK, "another-device"))
        self.assertIsNone(from_connect(TRACK, ""))
        self.assertIsNone(from_connect({**TRACK, "device": None}, "tv-device-id"))
        self.assertIsNone(from_connect({**TRACK, "device": {"id": "tv-device-id", "is_active": False}},
                                       "tv-device-id"))

    def test_paused_and_nonmusic_remote_playback_not_selected(self):
        self.assertIsNone(from_connect({**TRACK, "is_playing": False}, "tv-device-id"))
        self.assertIsNone(from_connect({**TRACK, "currently_playing_type": "episode"},
                                       "tv-device-id"))


class PhoneToTVBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {**load_config(), "spotify_source": "connect",
                    "spotify_connect_device_id": "tv-device-id"}
        self.store = Store(Path(self.tmp.name) / "matches.sqlite3")
        self.addCleanup(self.store.close)
        self.track = Track("0" * 22, "Papaoutai", ("Stromae",), 232, "Racine carrée")
        self.video = {"id": "A" * 11, "title": "Papaoutai (Official Video)",
                      "channel": "Stromae", "channel_is_verified": True,
                      "duration": 232, "live_status": None, "view_count": 500,
                      "details_checked": True}
        self.store.remember(self.track, self.cfg, self.video)
        self.source = Mock()
        self.source.name = "connect"
        self.source.current.return_value = self.track
        self.tv = Mock()
        self.tv.check_control.return_value = {"generation": "test"}
        def send(video_id, *, track_id, generation):
            self.store.record_handled(track_id, (self.cfg["tv_target"],
                                                  self.cfg["smarttube_package"]), video_id, "sent")
            return True
        self.tv.send.side_effect = send
        root = patch("main.ROOT", Path(self.tmp.name))
        root.start()
        self.addCleanup(root.stop)
        self.bridge = Bridge(self.cfg, self.source, self.tv, self.store)

    def test_phone_selected_tv_launches_video_once(self):
        with patch("main.score", return_value=Mock(accepted=True, score=120, tier=1)):
            self.assertEqual(self.bridge.step(), "sent")
            self.assertEqual(self.bridge.step(), "duplicate")
        self.tv.claim_for_connect.assert_called_once_with(self.track.id)
        self.tv.send.assert_called_once()

    def test_ignores_no_playback_on_target_tv(self):
        self.source.current.return_value = None
        self.assertEqual(self.bridge.step(), "idle")
        self.tv.claim_for_connect.assert_not_called()
        self.tv.send.assert_not_called()

    def test_new_phone_track_rearms_session(self):
        other = Track("1" * 22, "Another", ("Artist",), 200)
        self.store.remember(other, self.cfg, self.video)
        with patch("main.score", return_value=Mock(accepted=True, score=120, tier=1)):
            self.assertEqual(self.bridge.step(), "sent")
            self.source.current.return_value = other
            self.assertEqual(self.bridge.step(), "sent")
        self.assertEqual(self.tv.claim_for_connect.call_count, 2)

    def test_remote_clip_end_does_not_skip_unrelated_tv_media_session(self):
        tv = SmartTube(self.cfg, self.store)
        with self.assertRaises(ManualOverride):
            tv.next_on_spotify("A" * 11)
        self.assertTrue(self.store.get_state("tv_control")["manual_override"])


if __name__ == "__main__":
    unittest.main()
