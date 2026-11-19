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

    def log_message(self, format: str, *args: object) -> None:
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

    def test_a_standard_url_without_a_checksums_file_is_refused(
        self, server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server.serve("/vm.img", b"hello world")
        monkeypatch.setattr(qemu_image, "get_download_url", lambda path: server.url("/vm.img"))

        with pytest.raises(OSError, match="No checksum could be verified"):
            qemu_image.ensure_image(tmp_path / "vm.img")

        assert not (tmp_path / "vm.img").exists()

    def test_a_custom_url_without_a_pinned_checksum_is_refused(
        self,
        server: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        server.serve("/vm.img", b"hello world")
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_URL, server.url("/vm.img"))

        with pytest.raises(OSError, match=qemu_image.ENV_VM_IMAGE_SHA256):
            qemu_image.ensure_image(tmp_path / "vm.img")

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

    def test_a_cached_sidecar_does_not_override_a_new_pinned_digest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        image = tmp_path / "vm.img"
        image.write_bytes(b"old image")
        qemu_image._write_sidecar(image, "sha256", hashlib.sha256(b"old image").hexdigest())
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_SHA256, "0" * 64)
        with pytest.raises(OSError, match="[Cc]hecksum mismatch"):
            qemu_image.ensure_image(image)

    @pytest.mark.parametrize("matches", [False, True])
    def test_legacy_sidecar_for_standard_name_requires_upstream_verification(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, matches: bool
    ) -> None:
        image = tmp_path / "debian-12-generic-amd64.qcow2"
        image.write_bytes(b"old custom image")
        stat = image.stat()
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        qemu_image._sidecar_path(image).write_text(
            f"sha256:{digest}:{stat.st_size}:{stat.st_mtime_ns}\n", encoding="utf-8"
        )
        upstream_digest = digest if matches else "0" * 64
        monkeypatch.setattr(qemu_image, "_neighbor_checksum", lambda url: ("sha256", upstream_digest))
        if matches:
            assert qemu_image.ensure_image(image) == image
        else:
            with pytest.raises(OSError, match="[Cc]hecksum mismatch"):
                qemu_image.ensure_image(image)

    @pytest.mark.parametrize("custom_url", [False, True])
    def test_a_legacy_custom_sidecar_without_a_pin_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, custom_url: bool
    ) -> None:
        image = tmp_path / ("debian-12-generic-amd64.qcow2" if custom_url else "custom.img")
        image.write_bytes(b"custom image")
        qemu_image._write_sidecar(image, "sha256", hashlib.sha256(b"custom image").hexdigest())
        if custom_url:
            monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_URL, "https://example.com/image")
        with pytest.raises(OSError, match=qemu_image.ENV_VM_IMAGE_SHA256):
            qemu_image.ensure_image(image)
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_SHA256, hashlib.sha256(b"custom image").hexdigest())
        assert qemu_image.ensure_image(image) == image

    def test_a_custom_cached_image_without_a_sidecar_or_digest_is_refused(self, tmp_path: Path) -> None:
        image = tmp_path / "vm.img"
        image.write_bytes(b"whatever was there before this feature existed")
        with pytest.raises(OSError, match=qemu_image.ENV_VM_IMAGE_SHA256):
            qemu_image.ensure_image(image)

    def test_custom_cached_image_with_pinned_digest_is_verified(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        image = tmp_path / "vm.img"
        image.write_bytes(b"custom image")
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_SHA256, hashlib.sha256(b"custom image").hexdigest())
        assert qemu_image.ensure_image(image) == image
        assert qemu_image._sidecar_path(image).is_file()

    def test_cached_image_with_wrong_pinned_digest_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        image = tmp_path / "vm.img"
        image.write_bytes(b"custom image")
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_SHA256, "0" * 64)
        with pytest.raises(OSError, match="[Cc]hecksum mismatch"):
            qemu_image.ensure_image(image)
        assert image.read_bytes() == b"custom image"

    def test_standard_cached_image_is_verified_against_its_own_upstream(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        image = tmp_path / "debian-12-generic-amd64.qcow2"
        image.write_bytes(b"standard image")
        digest = hashlib.sha512(b"standard image").hexdigest()
        monkeypatch.setattr(qemu_image, "_neighbor_checksum", lambda url: ("sha512", digest))
        assert qemu_image.ensure_image(image) == image
        assert qemu_image._sidecar_path(image).is_file()

    def test_standard_cached_image_is_refused_offline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        image = tmp_path / "debian-12-generic-amd64.qcow2"
        image.write_bytes(b"standard image")
        monkeypatch.setattr(qemu_image, "_neighbor_checksum", lambda url: None)
        with pytest.raises(OSError, match="migrate-cache"):
            qemu_image.ensure_image(image)

    def test_standard_cached_image_mismatching_upstream_is_preserved_and_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        image = tmp_path / "debian-12-generic-amd64.qcow2"
        image.write_bytes(b"old image")
        monkeypatch.setattr(qemu_image, "_neighbor_checksum", lambda url: ("sha256", "0" * 64))
        with pytest.raises(OSError, match="[Cc]hecksum mismatch"):
            qemu_image.ensure_image(image)
        assert image.read_bytes() == b"old image"
        assert not qemu_image._sidecar_path(image).exists()


class TestUpstreamUrlForCachedName:
    def test_a_debian_image_name_resolves_to_the_debian_url(self) -> None:
        url = qemu_image._upstream_url_for_cached_name("debian-12-generic-amd64.qcow2")

        assert url == f"{qemu_image.DEBIAN_CLOUD_BASE}/debian-12-generic-amd64.qcow2"

    def test_an_ubuntu_image_name_resolves_to_its_own_release_not_the_current_one(self) -> None:
        """23.04 is the image for Python 3.11, not the interpreter running this test."""
        url = qemu_image._upstream_url_for_cached_name("ubuntu-23.04-server-cloudimg-amd64.img")

        assert url == f"{qemu_image.UBUNTU_CLOUD_RELEASES_BASE}/23.04/release/ubuntu-23.04-server-cloudimg-amd64.img"

    def test_a_retired_codename_image_resolves_to_nothing(self) -> None:
        """`resolute` tracked a devel series and is no longer in PYTHON_VERSION_TO_UBUNTU_IMAGE: its
        `current/` directory has moved on since any such cached image was fetched, so resolving a URL
        for it would compare against bytes that were never the ones cached."""
        assert qemu_image._upstream_url_for_cached_name("resolute-server-cloudimg-amd64.img") is None

    def test_an_unknown_name_resolves_to_nothing(self) -> None:
        assert qemu_image._upstream_url_for_cached_name("my-custom-image.qcow2") is None


class TestHashFile:
    def test_matches_hashlib_computed_directly(self, tmp_path: Path) -> None:
        content = b"some image bytes" * 1000
        path = tmp_path / "image.bin"
        path.write_bytes(content)

        assert qemu_image._hash_file(path, "sha256") == hashlib.sha256(content).hexdigest()

    def test_reads_in_chunks_not_whole(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(qemu_image, "_HASH_CHUNK_BYTES", 4)
        content = b"0123456789abcdef"
        path = tmp_path / "image.bin"
        path.write_bytes(content)

        assert qemu_image._hash_file(path, "sha256") == hashlib.sha256(content).hexdigest()


class TestVerifyCachedImage:
    def test_a_matching_image_is_verified_and_gets_a_sidecar(self, server: Any, tmp_path: Path) -> None:
        content = b"a cached image, fetched before the checksum feature existed"
        image = tmp_path / "vm.img"
        image.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        server.serve("/SHA256SUMS", f"{digest} *vm.img\n".encode())

        outcome = qemu_image.verify_cached_image(image, url=server.url("/vm.img"))

        assert outcome == "verified"
        sidecar = tmp_path / "vm.img.sha256"
        assert sidecar.is_file()
        assert sidecar.read_text().startswith(f"sha256:{digest}:")
        assert image.read_bytes() == content, "the image itself is never rewritten"

    def test_a_mismatching_image_is_refused_and_gets_no_sidecar(self, server: Any, tmp_path: Path) -> None:
        content = b"a cached image that does not match what upstream now publishes"
        image = tmp_path / "vm.img"
        image.write_bytes(content)
        server.serve("/SHA256SUMS", f"{'0' * 64} *vm.img\n".encode())

        outcome = qemu_image.verify_cached_image(image, url=server.url("/vm.img"))

        assert outcome == "mismatch"
        assert not (tmp_path / "vm.img.sha256").exists()
        assert image.read_bytes() == content, "a refused image is never deleted or modified"

    def test_no_checksums_file_is_unavailable_not_an_error(self, server: Any, tmp_path: Path) -> None:
        image = tmp_path / "vm.img"
        image.write_bytes(b"content")

        outcome = qemu_image.verify_cached_image(image, url=server.url("/vm.img"))

        assert outcome == "unavailable"
        assert not (tmp_path / "vm.img.sha256").exists()

    def test_a_name_with_no_derivable_url_is_unavailable_without_any_network_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            qemu_image, "_neighbor_checksum", lambda url: pytest.fail("must not even try to fetch anything")
        )
        image = tmp_path / "my-custom-image.qcow2"
        image.write_bytes(b"content")

        assert qemu_image.verify_cached_image(image) == "unavailable"


class TestMigrateImageCache:
    def test_a_cached_image_matching_its_upstream_sums_is_verified(
        self, server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qemu_image, "DEBIAN_CLOUD_BASE", server.base_url)
        content = b"a real debian cloud image's bytes, cached before this feature existed"
        image = tmp_path / "debian-12-generic-amd64.qcow2"
        image.write_bytes(content)
        digest = hashlib.sha512(content).hexdigest()
        server.serve("/SHA512SUMS", f"{digest}  debian-12-generic-amd64.qcow2\n".encode())

        results = qemu_image.migrate_image_cache(tmp_path)

        assert results == {image: "verified"}
        assert (tmp_path / "debian-12-generic-amd64.qcow2.sha256").is_file()

    def test_an_image_that_already_has_a_sidecar_is_left_alone(self, tmp_path: Path) -> None:
        image = tmp_path / "debian-12-generic-amd64.qcow2"
        image.write_bytes(b"content")
        (tmp_path / "debian-12-generic-amd64.qcow2.sha256").write_text("sha256:abc:7:1\n", encoding="utf-8")

        assert qemu_image.migrate_image_cache(tmp_path) == {}

    def test_non_image_files_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "README.txt").write_text("not an image\n", encoding="utf-8")

        assert qemu_image.migrate_image_cache(tmp_path) == {}

    def test_a_missing_directory_returns_an_empty_result_without_raising(self, tmp_path: Path) -> None:
        assert qemu_image.migrate_image_cache(tmp_path / "absent") == {}
