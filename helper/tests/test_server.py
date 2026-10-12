import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class ValidationTests(unittest.TestCase):
    def test_valid_video_requests(self):
        self.assertEqual(server.validate_request({"bvid": "BV1dRYP6oEtB"}), ("BV1dRYP6oEtB", None, None))
        self.assertEqual(server.validate_request({"bvid": "BV1dRYP6oEtB", "p": 2}), ("BV1dRYP6oEtB", 2, None))
        self.assertEqual(server.validate_request({"bvid": "BV1dRYP6oEtB", "cid": 123}), ("BV1dRYP6oEtB", None, 123))

    def test_rejects_url_and_bad_page_values(self):
        invalid = [
            {"bvid": "https://evil.test/"},
            {"bvid": "BV1dRYP6oEtB;rm -rf ."},
            {"bvid": "BV1dRYP6oEtB", "p": True},
            {"bvid": "BV1dRYP6oEtB", "p": 0},
            {"bvid": "BV1dRYP6oEtB", "p": 1001},
            {"bvid": "BV1dRYP6oEtB", "cid": -1},
            {"bvid": "BV1dRYP6oEtB", "p": 1, "cid": 123},
            {"bvid": "BV1dRYP6oEtB", "url": "https://evil.test/"},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(server.ClientError):
                server.validate_request(payload)

    def test_youtube_request_accepts_only_video_id(self):
        video = server.parse_video_request({"youtubeId": "dQw4w9WgXcQ"})
        self.assertEqual(video, server.VideoRequest(None, youtube_id="dQw4w9WgXcQ"))
        self.assertEqual(video.platform, "youtube")
        self.assertEqual(server.parse_video_request({"bvid": "BV1dRYP6oEtB"}).platform, "bilibili")

    def test_youtube_request_rejects_urls_and_mixed_fields(self):
        invalid = [
            {"youtubeId": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            {"youtubeId": "dQw4w9WgXc"},
            {"youtubeId": "dQw4w9WgXcQ;"},
            {"youtubeId": "dQw4w9WgXcQ", "bvid": "BV1dRYP6oEtB"},
            {"youtubeId": "dQw4w9WgXcQ", "p": 1},
            {"youtubeId": 123},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(server.ClientError):
                server.parse_video_request(payload)

    def test_youtube_cache_has_distinct_platform_identity(self):
        bili = server.VideoRequest("BV1dRYP6oEtB", 1)
        youtube = server.VideoRequest(None, youtube_id="dQw4w9WgXcQ")
        segments = [{"from": 0, "to": 1, "content": "hello"}]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            server.write_cache(root, bili, segments)
            server.write_cache(root, youtube, segments)
            self.assertNotEqual(server.cache_path(root, bili), server.cache_path(root, youtube))
            self.assertEqual(server.read_cache(root, bili), segments)
            self.assertEqual(server.read_cache(root, youtube), segments)
            self.assertIsNone(server.read_cache(root, server.VideoRequest(None, youtube_id="dQw4w9WgXcR")))
            cached = json.loads(server.cache_path(root, youtube).read_text(encoding="utf-8"))
            self.assertEqual(cached["platform"], "youtube")
            self.assertEqual(cached["youtubeId"], youtube.youtube_id)

    def test_youtube_metadata_id_must_match_before_download(self):
        video = server.VideoRequest(None, youtube_id="dQw4w9WgXcQ")
        canonical = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        with patch.object(server, "_check_dependencies"), \
             patch.object(server, "_run_metadata", return_value={"id": "differentId", "duration": 10}) as metadata, \
             patch.object(server, "_download_audio") as download:
            with self.assertRaisesRegex(server.ClientError, "different YouTube video"):
                server.transcribe_video(video, lambda *_: None)
            metadata.assert_called_once_with(canonical)
            download.assert_not_called()

    def test_origin_policy(self):
        self.assertTrue(server.allowed_origin(None))
        self.assertTrue(server.allowed_origin("chrome-extension://" + "a" * 32))
        self.assertFalse(server.allowed_origin("null"))
        self.assertFalse(server.allowed_origin("https://bilibili.com"))
        self.assertFalse(server.allowed_origin("chrome-extension://" + "a" * 32 + ".evil.test"))

    def test_cid_resolves_only_with_matching_bvid(self):
        body = {"code": 0, "data": {"bvid": "BV1dRYP6oEtB", "pages": [{"cid": 100}, {"cid": 200}]}}
        with patch.object(server.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(body).encode())):
            self.assertEqual(server.resolve_page("BV1dRYP6oEtB", 200), 2)
        body["data"]["bvid"] = "BV1aaaaaaaaa"
        with patch.object(server.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(body).encode())):
            with self.assertRaises(server.ClientError):
                server.resolve_page("BV1dRYP6oEtB", 200)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

        def fake_worker(_video, update):
            update(55, "transcribing")
            return [{"from": 0.0, "to": 1.5, "content": "测试"}]

        manager = server.JobManager(Path(self.temp.name), fake_worker)

        class QuietHandler(server.Handler):
            def log_message(self, _format, *_args):
                pass

        QuietHandler.manager = manager
        self.http = ThreadingHTTPServer((server.HOST, 0), QuietHandler)
        self.http.daemon_threads = True
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://{server.HOST}:{self.http.server_port}"
        self.manager = manager

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def _request(self, path, body=None, origin=None):
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if origin:
            headers["Origin"] = origin
        request = urllib.request.Request(
            self.url + path, data=json.dumps(body).encode() if body is not None else None, headers=headers
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.load(response)

    def test_async_job_and_cache(self):
        status, first = self._request("/transcribe", {"bvid": "BV1dRYP6oEtB", "p": 1})
        self.assertEqual(status, 202)
        self.assertIn("job_id", first)
        self.manager.pending.join()
        status, job = self._request("/jobs/" + first["job_id"])
        self.assertEqual(status, 200)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["segments"][0]["content"], "测试")
        status, cached = self._request("/transcribe", {"bvid": "BV1dRYP6oEtB", "p": 1})
        self.assertEqual(status, 200)
        self.assertEqual(cached["segments"], job["segments"])

    def test_youtube_http_job_and_cache(self):
        request = {"youtubeId": "dQw4w9WgXcQ"}
        status, first = self._request("/transcribe", request)
        self.assertEqual(status, 202)
        self.manager.pending.join()
        status, job = self._request("/jobs/" + first["job_id"])
        self.assertEqual(status, 200)
        self.assertEqual(job["status"], "done")
        status, cached = self._request("/transcribe", request)
        self.assertEqual(status, 200)
        self.assertEqual(cached["segments"], job["segments"])

    def test_youtube_http_rejects_mixed_ids(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self._request("/transcribe", {"youtubeId": "dQw4w9WgXcQ", "bvid": "BV1dRYP6oEtB"})
        self.assertEqual(error.exception.code, 400)

    def test_forbidden_origin(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self._request("/health", origin="https://evil.test")
        self.assertEqual(error.exception.code, 403)

    def test_invalid_bvid(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self._request("/transcribe", {"bvid": "https://evil.test/"})
        self.assertEqual(error.exception.code, 400)

    def test_failed_job_reports_error(self):
        def failing_worker(_video, _update):
            raise server.ClientError("audio unavailable")

        manager = server.JobManager(Path(self.temp.name), failing_worker)
        response, status = manager.submit(server.VideoRequest("BV1dRYP6oEtB", 2))
        self.assertEqual(status, 202)
        manager.pending.join()
        job = manager.get(response["job_id"])
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["error"], "audio unavailable")


if __name__ == "__main__":
    unittest.main()
