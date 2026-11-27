from hashlib import sha256
import json
import unittest

from aame.youtube_protocol import begin, confirm_processing, processing_request, session_from_response
from aame.youtube_shorts import Upload


class ProtocolTest(unittest.TestCase):
    data = b"synthetic approved bytes"
    url = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=fixture"

    def session(self, url=None):
        return session_from_response(200, {"Location": url or self.url},
                                     size=len(self.data), approved_digest=sha256(self.data).hexdigest())

    def test_explicit_disclosures_and_session_metadata(self):
        upload = Upload("channel", "v1", sha256(self.data).hexdigest(), "Example",
                        "private", False, True)
        request = begin(upload, category_id="22", contains_synthetic_media=False, size=len(self.data))
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.headers["X-Upload-Content-Length"], str(len(self.data)))
        self.assertEqual(json.loads(request.body)["status"], {
            "privacyStatus": "private", "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": False,
        })

    def test_resumes_only_approved_artifact_and_offset(self):
        session = self.session()
        self.assertEqual(session.probe().headers["Content-Range"], f"bytes */{len(self.data)}")
        progress = session.progress(308, {"Range": "bytes=0-4"}, None)
        request = session.transfer(self.data, next_offset=progress.next_offset)
        self.assertEqual(request.body, self.data[5:])
        self.assertEqual(request.headers["Content-Range"], f"bytes 5-{len(self.data) - 1}/{len(self.data)}")
        with self.assertRaisesRegex(ValueError, "approved artifact"):
            session.transfer(b"x" * len(self.data))
        self.assertEqual(session.progress(404, {}, {}).state, "reconciliation_required")
        self.assertEqual(session.progress(308, {"Range": "bytes=1-4"}, {}).state,
                         "reconciliation_required")

    def test_rejects_off_origin_and_ambiguous_upload_locations(self):
        for url in (self.url.replace("www.googleapis.com", "www.googleapis.com.evil.org"),
                    self.url.replace("https:", "http:"), self.url + "&upload_id=other"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.session(url)

    def test_processing_must_match_video_channel_and_visibility(self):
        video_id = "abcdefghijk"
        payload = {"items": [{
            "id": video_id, "snippet": {"channelId": "channel"},
            "status": {"privacyStatus": "public", "uploadStatus": "processed"},
            "processingDetails": {"processingStatus": "succeeded"},
        }]}
        self.assertIn("processingDetails", processing_request(video_id).url)
        self.assertTrue(confirm_processing(payload, video_id=video_id,
                                           channel_id="channel", visibility="public"))
        self.assertFalse(confirm_processing(payload, video_id=video_id,
                                            channel_id="other", visibility="public"))
        self.assertFalse(confirm_processing(payload, video_id=video_id,
                                            channel_id="channel", visibility="private"))
