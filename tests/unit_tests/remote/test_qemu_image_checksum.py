# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Checksum verification of a downloaded QEMU image, and the checksum-sidecar cache.

Uses a disposable local HTTP server (not a mock) wherever the behaviour depends on real
transport semantics: a truncated connection does not necessarily raise inside
``urllib.request`` (confirmed empirically, see ``_download_once``'s comment), so that case
is reproduced over a real socket rather than assumed.
"""

import hashlib
import http.server
import threading
from pathlib import Path
from typing import Any

import pytest

from pysandboxes.remote import qemu_image


class _TestHTTPServer(http.server.ThreadingHTTPServer):
    """Route table the handler reads per request; routes/truncate_path live on the server."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.routes: dict[str, bytes] = {}
        self.truncate_path: str | None = None


class _Handler(http.server.BaseHTTPRequestHandler):
    server: _TestHTTPServer

    def do_GET(self) -> None:
        body = self.server.routes.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        if self.path == self.server.truncate_path:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body) * 10))  # lie: far more than sent
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def server() -> Any:
    class _Server:
        def __init__(self) -> None:
            self.httpd = _TestHTTPServer(("127.0.0.1", 0), _Handler)
            self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
            self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.thread.start()

        def serve(self, path: str, body: bytes) -> None:
            self.httpd.routes[path] = body

        def truncate(self, path: str, body: bytes) -> None:
            self.httpd.routes[path] = body
            self.httpd.truncate_path = path

        def url(self, path: str) -> str:
            return f"{self.base_url}{path}"

        def stop(self) -> None:
            self.httpd.shutdown()
            self.httpd.server_close()

    instance = _Server()
    yield instance
    instance.stop()


class TestDownloadImageChecksum:
    def test_a_correct_checksum_is_accepted(self, server: Any, tmp_path: Path) -> None:
        server.serve("/vm.img", b"hello world")
        digest = hashlib.sha256(b"hello world").hexdigest()

        result = qemu_image.download_image(
            tmp_path / "vm.img", server.url("/vm.img"), lambda *_: None, expected_checksum=("sha256", digest)
        )

        assert result.read_bytes() == b"hello world"

    def test_a_wrong_checksum_is_refused_after_one_retry_and_removes_the_partial(
        self, server: Any, tmp_path: Path
    ) -> None:
        server.serve("/vm.img", b"hello world")

        with pytest.raises(OSError, match="Checksum mismatch"):
            qemu_image.download_image(
                tmp_path / "vm.img",
                server.url("/vm.img"),
                lambda *_: None,
                expected_checksum=("sha256", "0" * 64),
            )

        assert not (tmp_path / "vm.img").exists()
        assert not (tmp_path / "vm.img.partial").exists()

    def test_a_truncated_download_is_refused_even_without_a_checksum(self, server: Any, tmp_path: Path) -> None:
        server.truncate("/vm.img", b"short")

        with pytest.raises(OSError, match="truncated"):
            qemu_image.download_image(tmp_path / "vm.img", server.url("/vm.img"), lambda *_: None)

        assert not (tmp_path / "vm.img").exists()
        assert not (tmp_path / "vm.img.partial").exists()


class TestFetchChecksumsText:
    def test_an_oversized_checksums_file_is_ignored_instead_of_read_in_full(
        self, server: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qemu_image, "CHECKSUMS_MAX_BYTES", 10)
        server.serve("/SHA256SUMS", b"x" * 1000)

        assert qemu_image._fetch_checksums_text(server.url("/SHA256SUMS")) is None


# A fixed Debian-style SHA512SUMS sample: GNU coreutils text-mode, two spaces before the name.
_SHA512_DIGEST_AMD64 = "ab" * 64
_SHA512_DIGEST_ARM64 = "cd" * 64
_DEBIAN_SHA512SUMS = (
    f"{_SHA512_DIGEST_AMD64}  debian-12-generic-amd64.qcow2\n{_SHA512_DIGEST_ARM64}  debian-12-generic-arm64.qcow2\n"
)

# A fixed Ubuntu-style SHA256SUMS sample: binary-mode marker ("*name"), as Ubuntu publishes it.
_SHA256_DIGEST_AMD64 = "ef" * 32
_UBUNTU_SHA256SUMS = f"{_SHA256_DIGEST_AMD64} *ubuntu-24.04-server-cloudimg-amd64.img\n"


class TestChecksumsCandidatesForHost:
    def test_debian_is_pinned_to_sha512sums(self) -> None:
        assert qemu_image._checksums_candidates_for_host("cloud.debian.org") == [("sha512", "SHA512SUMS")]

    def test_ubuntu_is_pinned_to_sha256sums(self) -> None:
        assert qemu_image._checksums_candidates_for_host("cloud-images.ubuntu.com") == [("sha256", "SHA256SUMS")]

    def test_an_unknown_host_tries_both_conventions(self) -> None:
        assert qemu_image._checksums_candidates_for_host("example.com") == [
            ("sha256", "SHA256SUMS"),
            ("sha512", "SHA512SUMS"),
        ]


class TestParseChecksumLine:
    def test_a_debian_style_sha512sums_line_is_matched(self) -> None:
        digest = qemu_image._parse_checksum_line(_DEBIAN_SHA512SUMS, "debian-12-generic-arm64.qcow2")

        assert digest == _SHA512_DIGEST_ARM64

    def test_an_ubuntu_style_binary_mode_line_is_matched(self) -> None:
        digest = qemu_image._parse_checksum_line(_UBUNTU_SHA256SUMS, "ubuntu-24.04-server-cloudimg-amd64.img")

        assert digest == _SHA256_DIGEST_AMD64

    def test_the_digest_is_lowercased(self) -> None:
        text = f"{_SHA512_DIGEST_AMD64.upper()}  debian-12-generic-amd64.qcow2\n"

        assert qemu_image._parse_checksum_line(text, "debian-12-generic-amd64.qcow2") == _SHA512_DIGEST_AMD64

    def test_a_filename_absent_from_the_listing_is_none(self) -> None:
        assert qemu_image._parse_checksum_line(_DEBIAN_SHA512SUMS, "debian-12-generic-ppc64el.qcow2") is None

    def test_a_filename_that_is_only_a_prefix_of_a_listed_one_does_not_match(self) -> None:
        assert qemu_image._parse_checksum_line(_DEBIAN_SHA512SUMS, "debian-12-generic-amd64") is None


class TestNeighborChecksumAndResolveExpectedChecksum:
    def test_a_debian_sha512sums_neighbor_is_found_and_parsed(self, server: Any) -> None:
        # No /SHA256SUMS route: it 404s, so the fallback tries /SHA512SUMS next, which is what matters here.
        server.serve("/SHA512SUMS", _DEBIAN_SHA512SUMS.encode())

        result = qemu_image._neighbor_checksum(server.url("/debian-12-generic-amd64.qcow2"))

        assert result == ("sha512", _SHA512_DIGEST_AMD64)

    def test_an_ubuntu_sha256sums_neighbor_is_found_and_parsed(self, server: Any) -> None:
        server.serve("/SHA256SUMS", _UBUNTU_SHA256SUMS.encode())

        result = qemu_image._neighbor_checksum(server.url("/ubuntu-24.04-server-cloudimg-amd64.img"))

        assert result == ("sha256", _SHA256_DIGEST_AMD64)

    def test_no_checksums_file_at_all_is_none(self, server: Any) -> None:
        assert qemu_image._neighbor_checksum(server.url("/vm.img")) is None

    def test_resolve_expected_checksum_prefers_the_pinned_env_over_the_neighbor_file(
        self, server: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server.serve("/SHA256SUMS", _UBUNTU_SHA256SUMS.encode())
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_SHA256, "11" * 32)

        result = qemu_image._resolve_expected_checksum(server.url("/ubuntu-24.04-server-cloudimg-amd64.img"))

        assert result == ("sha256", "11" * 32)

    def test_resolve_expected_checksum_falls_back_to_the_neighbor_file(
        self, server: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(qemu_image.ENV_VM_IMAGE_SHA256, raising=False)
        server.serve("/SHA512SUMS", _DEBIAN_SHA512SUMS.encode())

        result = qemu_image._resolve_expected_checksum(server.url("/debian-12-generic-arm64.qcow2"))

        assert result == ("sha512", _SHA512_DIGEST_ARM64)


class TestEnsureImageChecksum:
    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(qemu_image.ENV_VM_IMAGE_URL, raising=False)
        monkeypatch.delenv(qemu_image.ENV_VM_IMAGE_BASE_URL, raising=False)
        monkeypatch.delenv(qemu_image.ENV_VM_IMAGE_SHA256, raising=False)
        qemu_image._WARNED_ONCE.clear()

    def test_a_standard_url_without_a_checksums_file_is_refused(
        self, server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server.serve("/vm.img", b"hello world")
        monkeypatch.setattr(qemu_image, "get_download_url", lambda path: server.url("/vm.img"))

        with pytest.raises(OSError, match="No checksum could be verified"):
            qemu_image.ensure_image(tmp_path / "vm.img")

        assert not (tmp_path / "vm.img").exists()

    def test_a_custom_url_without_a_checksums_file_is_accepted_with_one_warning(
        self,
        server: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        server.serve("/vm.img", b"hello world")
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_URL, server.url("/vm.img"))

        with caplog.at_level("WARNING"):
            path = qemu_image.ensure_image(tmp_path / "vm.img")

        assert path.read_bytes() == b"hello world"
        assert "image not verified" in caplog.text

    def test_the_pinned_env_checksum_accepts_a_matching_digest(
        self, server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server.serve("/vm.img", b"hello world")
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_URL, server.url("/vm.img"))
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_SHA256, hashlib.sha256(b"hello world").hexdigest())

        assert qemu_image.ensure_image(tmp_path / "vm.img").read_bytes() == b"hello world"

    def test_the_pinned_env_checksum_refuses_a_mismatching_digest(
        self, server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server.serve("/vm.img", b"hello world")
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_URL, server.url("/vm.img"))
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_SHA256, "0" * 64)

        with pytest.raises(OSError, match="Checksum mismatch"):
            qemu_image.ensure_image(tmp_path / "vm.img")

    def test_a_matching_sidecar_skips_rehashing_the_cached_image(
        self, server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server.serve("/vm.img", b"hello world")
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_URL, server.url("/vm.img"))
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_SHA256, hashlib.sha256(b"hello world").hexdigest())
        image = tmp_path / "vm.img"
        qemu_image.ensure_image(image)
        assert (tmp_path / "vm.img.sha256").is_file()
        monkeypatch.setattr(
            qemu_image, "download_image", lambda *a, **k: pytest.fail("should not re-download a cached, verified image")
        )

        assert qemu_image.ensure_image(image) == image

    def test_an_inconsistent_sidecar_triggers_a_fresh_verified_download(
        self, server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server.serve("/vm.img", b"hello world")
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_URL, server.url("/vm.img"))
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_SHA256, hashlib.sha256(b"hello world").hexdigest())
        image = tmp_path / "vm.img"
        image.write_bytes(b"stale content, not what the sidecar below describes")
        (tmp_path / "vm.img.sha256").write_text("sha256:deadbeef:999999:123456789\n", encoding="utf-8")

        assert qemu_image.ensure_image(image).read_bytes() == b"hello world"
        assert (tmp_path / "vm.img.sha256").is_file()

    def test_a_cached_image_without_a_sidecar_is_accepted_with_one_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        image = tmp_path / "vm.img"
        image.write_bytes(b"whatever was there before this feature existed")

        with caplog.at_level("WARNING"):
            assert qemu_image.ensure_image(image) == image

        assert "without a checksum sidecar" in caplog.text
