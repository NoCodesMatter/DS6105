"""Downloader regression tests; all network calls and source files are isolated."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import requests
    import download as downloader
except ModuleNotFoundError as exc:
    if exc.name != "requests":
        raise
    downloader = None


@unittest.skipIf(downloader is None, "Install requirements-download.txt to test the optional downloader")
class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset, self.label = downloader.DATASETS[0]
        self.raw = self.root / "data/raw/hdb" / f"{self.dataset}.csv"
        self.manifest = self.root / "data/manifests/hdb_sources.json"
        self.content = b"month,resale_price\n2015-01,123.00\n"
        self.object_url = ("https://s3.ap-southeast-1.amazonaws.com/"
                           f"table-downloads-ingest.data.gov.sg/{self.dataset}/frozen.csv")
        self.signed_url = self.object_url + "?X-Amz-Signature=SECRET"
        self.session = MagicMock()
        for patcher in (patch.object(downloader, "DATASETS", ((self.dataset, self.label),)),
                        patch.object(downloader.requests, "Session", return_value=self.session),
                        patch.object(downloader.time, "sleep")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def response(self, status=200, data=None, chunks=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        response.json.return_value = {"code": 0, "data": data if data is not None else {}}
        response.iter_content.return_value = iter(chunks if chunks is not None else [self.content])
        return response

    def api_responses(self, url=None):
        return [self.response(data={"name": "Fixture"}), self.response(),
                self.response(data={"url": url or self.signed_url})]

    def locked(self, raw=False):
        entry = {"dataset_id": self.dataset, "label": self.label,
                 "path": self.raw.relative_to(self.root).as_posix(),
                 "sha256": hashlib.sha256(self.content).hexdigest(),
                 "bytes": len(self.content), "rows": 1, "header": ["month", "resale_price"],
                 "download_object_url": self.object_url,
                 "snapshot_utc": "2026-10-18T00:00:00+00:00"}
        manifest = {"collection_url": "https://data.gov.sg/collections/189/view", "sources": [entry]}
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        if raw:
            self.raw.parent.mkdir(parents=True, exist_ok=True)
            self.raw.write_bytes(self.content)
        return manifest

    def run_download(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return downloader.download(self.root)

    def assert_clean(self):
        self.assertEqual(list(self.root.rglob("*.part")), [])

    def test_matching_local_snapshot_needs_no_network(self):
        self.locked(raw=True)
        original = self.manifest.read_bytes()
        self.run_download()
        self.session.get.assert_not_called()
        self.session.close.assert_called_once()
        self.assertEqual(self.manifest.read_bytes(), original)

    def test_corrupt_local_snapshot_is_not_overwritten(self):
        self.locked(raw=True)
        self.raw.write_bytes(b"original but corrupt")
        original = self.manifest.read_bytes()
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.run_download()
        self.session.get.assert_not_called()
        self.assertEqual(self.raw.read_bytes(), b"original but corrupt")
        self.assertEqual(self.manifest.read_bytes(), original)

    def test_missing_frozen_raw_restores_pinned_object_without_rewriting_manifest(self):
        self.locked()
        original = self.manifest.read_bytes()
        self.session.get.return_value = self.response()
        self.run_download()
        self.session.get.assert_called_once_with(self.object_url, stream=True,
                                                  timeout=(15, 120), allow_redirects=False)
        self.assertEqual(self.raw.read_bytes(), self.content)
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assert_clean()

    def test_private_pinned_object_falls_back_to_api_but_preserves_lock(self):
        self.locked()
        original = self.manifest.read_bytes()
        self.session.get.side_effect = [self.response(403), *self.api_responses(), self.response()]
        self.run_download()
        self.assertEqual(self.raw.read_bytes(), self.content)
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assertEqual(self.session.get.call_count, 5)
        self.assert_clean()

    def test_changed_live_data_cannot_replace_frozen_snapshot(self):
        self.locked()
        original = self.manifest.read_bytes()
        self.session.get.side_effect = [self.response(404), *self.api_responses(),
                                       self.response(chunks=[self.content.replace(b"123.00", b"456.00")])]
        with self.assertRaisesRegex(ValueError, "NEW snapshot root"):
            self.run_download()
        self.assertFalse(self.raw.exists())
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assert_clean()

    def test_api_retries_transport_errors_and_strips_signed_credentials(self):
        self.session.get.side_effect = [requests.Timeout("temporary"), *self.api_responses(), self.response()]
        manifest = self.run_download()
        self.assertEqual(self.session.get.call_count, 5)
        self.assertEqual(self.raw.read_bytes(), self.content)
        self.assertEqual(manifest["sources"][0]["download_object_url"], self.object_url)
        self.assertNotIn("SECRET", self.manifest.read_text(encoding="utf-8"))
        self.assert_clean()

    def test_official_initiate_and_poll_201_responses_are_accepted(self):
        self.session.get.side_effect = [self.response(200, data={"name": "Fixture"}),
                                       self.response(201),
                                       self.response(201, data={"url": self.signed_url}),
                                       self.response()]
        self.run_download()
        self.assertEqual(self.raw.read_bytes(), self.content)
        self.assertEqual(self.session.get.call_count, 4)
        self.assert_clean()

    def test_stream_interruption_restarts_instead_of_appending_partial_bytes(self):
        def broken_stream():
            yield self.content[:7]
            raise requests.exceptions.ChunkedEncodingError(self.signed_url)
        broken = self.response()
        broken.iter_content.return_value = broken_stream()
        self.session.get.side_effect = [*self.api_responses(), broken, self.response()]
        self.run_download()
        self.assertEqual(self.raw.read_bytes(), self.content)
        self.assert_clean()

    def test_csv_http_failures_retry_with_a_bound(self):
        self.session.get.side_effect = [*self.api_responses(),
                                       *[self.response(503) for _ in range(downloader.ATTEMPTS)]]
        with self.assertRaisesRegex(RuntimeError, "bounded retries"):
            self.run_download()
        self.assertEqual(self.session.get.call_count, 3 + downloader.ATTEMPTS)
        self.assertFalse(self.raw.exists())
        self.assertFalse(self.manifest.exists())
        self.assert_clean()

    def test_csv_transport_failure_cleans_up_without_leaking_signed_url(self):
        self.session.get.side_effect = [*self.api_responses(),
                                       *[requests.ConnectionError(self.signed_url)
                                         for _ in range(downloader.ATTEMPTS)]]
        with self.assertRaises(RuntimeError) as caught:
            self.run_download()
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertIsNone(caught.exception.__context__)
        self.assertFalse(self.raw.exists())
        self.assertFalse(self.manifest.exists())
        self.assert_clean()

    def test_api_transport_failures_stop_after_bounded_retries(self):
        self.session.get.side_effect = requests.ConnectionError("unavailable")
        with self.assertRaisesRegex(RuntimeError, "bounded retries"):
            self.run_download()
        self.assertEqual(self.session.get.call_count, downloader.ATTEMPTS)
        self.assertFalse(self.manifest.exists())
        self.assert_clean()

    def test_empty_csv_is_not_published(self):
        self.session.get.side_effect = [*self.api_responses(), self.response(chunks=[b""])]
        with self.assertRaisesRegex(ValueError, "Unexpected or empty"):
            self.run_download()
        self.assertFalse(self.raw.exists())
        self.assertFalse(self.manifest.exists())
        self.assert_clean()

    def test_untracked_raw_is_never_overwritten(self):
        self.raw.parent.mkdir(parents=True)
        self.raw.write_bytes(b"already here")
        self.session.get.side_effect = [*self.api_responses(), self.response()]
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            self.run_download()
        self.assertEqual(self.raw.read_bytes(), b"already here")
        self.assertFalse(self.manifest.exists())
        self.assert_clean()

    def test_manifest_rejects_duplicate_unknown_or_malformed_entries_before_network(self):
        good = self.locked()
        bad = [[], {"sources": {}}, {"sources": [None]},
               {"sources": good["sources"] * 2}]
        for field, value in (("dataset_id", "unknown"), ("path", "../other.csv"),
                             ("sha256", "not a hash"), ("rows", True), ("bytes", 0),
                             ("header", ["month", "month", "resale_price"]),
                             ("download_object_url", self.signed_url)):
            altered = copy.deepcopy(good)
            altered["sources"][0][field] = value
            bad.append(altered)
        for manifest in bad:
            with self.subTest(manifest=manifest):
                self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
                original = self.manifest.read_bytes()
                with self.assertRaises(ValueError):
                    self.run_download()
                self.assertEqual(self.manifest.read_bytes(), original)
                self.assertFalse(self.raw.exists())
        self.session.get.assert_not_called()

    def test_api_object_url_must_use_official_https_storage(self):
        for url in ("http://s3.ap-southeast-1.amazonaws.com/table-downloads-ingest.data.gov.sg/x",
                    "https://example.test/file.csv?signature=SECRET",
                    "https://s3.ap-southeast-1.amazonaws.com/another-bucket/file.csv"):
            with self.subTest(url=url):
                self.session.reset_mock()
                self.session.get.side_effect = self.api_responses(url)
                with self.assertRaisesRegex(ValueError, "official HTTPS storage"):
                    self.run_download()
                self.assertEqual(self.session.get.call_count, 3)
                self.assertFalse(self.raw.exists())
                self.assert_clean()

    def test_frozen_manifest_statistics_must_match_restored_bytes(self):
        manifest = self.locked()
        manifest["sources"][0]["rows"] = 2
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        original = self.manifest.read_bytes()
        self.session.get.return_value = self.response()
        with self.assertRaisesRegex(ValueError, "statistics disagree"):
            self.run_download()
        self.assertFalse(self.raw.exists())
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
