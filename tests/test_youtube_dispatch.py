from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, Mock

from aame.youtube_dispatch import DispatchError, UploadDispatcher
from aame.youtube_protocol import Request
from aame.youtube_shorts import Upload
from aame.youtube_transport import Response, TransportError, YouTubeTransport


SESSION = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=fixture"
MEDIA = b"fixture-video-bytes"
VIDEO = "abcdefghijk"
META = {"category_id": "22", "contains_synthetic_media": False}


class UploadDispatcherTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        self.mock = Mock(spec=["send"])
        self.driver = UploadDispatcher(self.path, self.mock)
        self.upload = Upload("owner-channel", "campaign-v1", sha256(MEDIA).hexdigest(),
                             "Fixture", "public", False, True)

    def initialize(self):
        return self.driver.initialize("job", self.upload, MEDIA, **META)

    def advance(self):
        return self.driver.advance("job", self.upload, MEDIA, **META)

    def test_lost_insert_never_restarts_even_after_database_reopen(self):
        self.mock.send.side_effect = TransportError("fixture timeout")
        self.assertEqual(self.initialize().state, "reconciliation_required")
        self.driver = UploadDispatcher(self.path, self.mock)
        self.assertEqual(self.initialize().state, "reconciliation_required")
        self.assertEqual(self.advance().state, "reconciliation_required")
        self.mock.send.assert_called_once()

    def test_lost_transfer_is_probed_and_resumed_from_confirmed_offset(self):
        status = {
            "items": [{
                "id": VIDEO, "snippet": {"channelId": "owner-channel"},
                "status": {"privacyStatus": "public", "uploadStatus": "processed"},
                "processingDetails": {"processingStatus": "succeeded"},
            }],
        }
        self.mock.send.side_effect = [
            Response(200, {"location": SESSION}, None),
            Response(308, {}, None),
            TransportError("fixture timeout after some bytes"),
            Response(308, {"range": "bytes=0-4"}, None),
            Response(201, {}, {"id": VIDEO}),
            Response(200, {}, {"items": []}),
            Response(200, {}, status),
        ]
        self.assertEqual(self.initialize().state, "session_saved")
        self.assertEqual(self.advance().state, "session_saved")
        self.driver = UploadDispatcher(self.path, self.mock)
        self.assertEqual(self.advance().state, "uploaded")
        self.assertEqual(self.advance().state, "uploaded")
        self.assertEqual(self.advance().state, "confirmed")
        self.assertEqual(self.advance().video_id, VIDEO)
        self.assertEqual(self.mock.send.call_count, 7)
        requests = [call.args[0] for call in self.mock.send.call_args_list]
        self.assertEqual(sum(request.method == "POST" for request in requests), 1)
        self.assertEqual(requests[4].body, MEDIA[5:])
        self.assertEqual(requests[4].url, SESSION)

    def test_session_expiry_and_changed_metadata_never_start_another_insert(self):
        self.mock.send.side_effect = [
            Response(200, {"location": SESSION}, None), Response(404, {}, None),
        ]
        self.initialize()
        self.assertEqual(self.advance().state, "reconciliation_required")
        with self.assertRaises(DispatchError):
            self.driver.initialize("job", replace(self.upload, visibility="private"), MEDIA, **META)
        with self.assertRaises(DispatchError):
            self.driver.advance("job", self.upload, b"tampered", **META)
        self.assertEqual(self.initialize().state, "reconciliation_required")
        self.assertEqual(self.mock.send.call_count, 2)


class TransportTest(unittest.TestCase):
    def test_guard_and_origin_are_checked_before_token_and_network(self):
        token = Mock(return_value="fixture-token")
        opener = Mock()
        guard = Mock(return_value=False)
        transport = YouTubeTransport(access_token=token, authorize=guard, opener=opener)
        with self.assertRaisesRegex(TransportError, "endpoint"):
            transport.send(Request("PUT", SESSION.replace("googleapis.com", "example.com"), {}))
        guard.assert_not_called()
        with self.assertRaisesRegex(TransportError, "authorization denied"):
            transport.send(Request("PUT", SESSION, {}))
        token.assert_not_called()
        opener.assert_not_called()

    def test_passes_short_lived_token_only_to_exact_https_endpoint(self):
        opener = MagicMock()
        response = opener.return_value
        response.code = 308
        response.headers = {"Range": "bytes=0-3"}
        response.read.return_value = b""
        transport = YouTubeTransport(
            access_token=lambda: "fixture-token", authorize=lambda request: True, opener=opener,
        )
        result = transport.send(Request("PUT", SESSION, {"Host": "example.com"}))
        wire = opener.call_args.args[0]
        self.assertEqual(wire.full_url, SESSION)
        self.assertEqual(wire.get_header("Authorization"), "Bearer fixture-token")
        self.assertIsNone(wire.get_header("Host"))
        self.assertEqual(result, Response(308, {"range": "bytes=0-3"}, None))
        self.assertNotIn("upload_id", repr(result))
