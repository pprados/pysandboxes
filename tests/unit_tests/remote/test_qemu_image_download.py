# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Download of the QEMU guest image: URL checks, progress reports, partial files and failure reporting."""

import io
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote import qemu_image


class _Response:
    def __init__(self, chunks: list[bytes], status: int = 200, length: str | None = None) -> None:
        self._chunks = list(chunks)
        self.status = status
        self.headers = {"Content-Length": length} if length is not None else {}

    def read(self, size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    responses: list[Any] = []

    def urlopen(request: Any, timeout: float) -> Any:
        seen.append({"url": request.full_url, "headers": dict(request.header_items()), "timeout": timeout})
        response = responses[0]
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(qemu_image.urllib.request, "urlopen", urlopen)
    seen.append({"responses": responses})
    return seen


def _serve(web: list[dict[str, Any]], response: Any) -> None:
    web[0]["responses"].append(response)


def _requests(web: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return web[1:]


class TestUrlValidation:
    @pytest.mark.parametrize(
        "url", ["http://host/image.img", "https://host/i.img", "HTTPS://HOST/I", "  https://h/i  "]
    )
    def test_http_and_https_are_accepted(self, url: str) -> None:
        assert qemu_image._validate_download_url(url) == url

    @pytest.mark.parametrize(
        "url", ["file:///etc/passwd", "ftp://host/i", "//host/i", "host/i.img", "", "javascript:x"]
    )
    def test_every_other_scheme_is_refused_with_the_start_of_the_url(self, url: str) -> None:
        with pytest.raises(ValueError, match="Only http:// and https:// are allowed"):
            qemu_image._validate_download_url(url)

    def test_a_long_refused_url_is_cut_in_the_message(self) -> None:
        with pytest.raises(ValueError) as error:
            qemu_image._validate_download_url("ftp://" + "x" * 200)

        assert "x" * 44 in str(error.value) and "x" * 45 not in str(error.value)


class TestDownloadUrl:
    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(qemu_image.ENV_VM_IMAGE_URL, raising=False)
        monkeypatch.delenv(qemu_image.ENV_VM_IMAGE_BASE_URL, raising=False)
        monkeypatch.setattr(qemu_image, "get_standard_download_url", lambda: "https://standard/img")

    def test_the_full_url_wins_and_is_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_URL, "  https://full/img  ")
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_BASE_URL, "https://base")

        assert qemu_image.get_download_url(Path("/x/name.img")) == "https://full/img"

    def test_the_base_url_gets_the_image_file_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_BASE_URL, "https://base/dir//")

        assert qemu_image.get_download_url(Path("/x/name.img")) == "https://base/dir/name.img"

    @pytest.mark.xfail(
        strict=True,
        reason="the base URL is tested for blankness but not stripped, unlike the full URL",
    )
    def test_a_padded_base_url_is_stripped_like_the_full_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_BASE_URL, " https://base/dir/ ")

        assert qemu_image.get_download_url(Path("/x/name.img")) == "https://base/dir/name.img"

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_variables_fall_through_to_the_standard_url(
        self, monkeypatch: pytest.MonkeyPatch, blank: str
    ) -> None:
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_URL, blank)
        monkeypatch.setenv(qemu_image.ENV_VM_IMAGE_BASE_URL, blank)

        assert qemu_image.get_download_url(Path("/x/name.img")) == "https://standard/img"


class TestProgressText:
    def _text(self, monkeypatch: pytest.MonkeyPatch, downloaded: int, total: int | None) -> str:
        stderr = io.StringIO()
        monkeypatch.setattr(qemu_image.sys, "stderr", stderr)

        qemu_image._default_progress_callback(downloaded, total)

        return stderr.getvalue()

    def test_a_known_size_shows_mebibytes_and_a_percentage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        text = self._text(monkeypatch, 512 * 1024, 2 * 1024 * 1024)

        assert text == "\r  Downloading VM image: 0.5 / 2.0 MiB (25%)"

    def test_the_percentage_never_exceeds_one_hundred(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._text(monkeypatch, 3 * 1024 * 1024, 2 * 1024 * 1024).endswith("(100%)")

    @pytest.mark.parametrize("total", [None, 0, -1])
    def test_an_unknown_size_shows_only_what_was_received(
        self, monkeypatch: pytest.MonkeyPatch, total: int | None
    ) -> None:
        assert self._text(monkeypatch, 1024 * 1024, total) == "\r  Downloading VM image: 1.0 MiB"

    def test_a_closed_stderr_does_not_break_the_download(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Closed:
            def write(self, text: str) -> int:
                raise OSError("closed")

            def flush(self) -> None:
                raise OSError("closed")

        monkeypatch.setattr(qemu_image.sys, "stderr", Closed())

        qemu_image._default_progress_callback(1, 2)


class TestDownload:
    def test_the_image_is_written_through_a_partial_file_and_reported(
        self, web: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qemu_image.sys, "stderr", io.StringIO())
        _serve(web, _Response([b"abc", b"defg"], length="7"))
        reports: list[tuple[int, int | None]] = []
        target = tmp_path / "images" / "vm.img"

        result = qemu_image.download_image(
            target, "https://host/vm.img", lambda done, total: reports.append((done, total))
        )

        assert result == target and target.read_bytes() == b"abcdefg"
        assert not (tmp_path / "images" / "vm.img.partial").exists()
        assert reports == [(3, 7), (7, 7), (7, 7)]

    def test_missing_parent_directories_are_created(self, web: list[dict[str, Any]], tmp_path: Path) -> None:
        _serve(web, _Response([b"x"]))
        target = tmp_path / "a" / "b" / "vm.img"

        qemu_image.download_image(target, "https://h/v", lambda *_: None)

        assert target.read_bytes() == b"x"

    def test_the_request_carries_an_agent_and_the_download_timeout(
        self, web: list[dict[str, Any]], tmp_path: Path
    ) -> None:
        _serve(web, _Response([b"x"]))

        qemu_image.download_image(tmp_path / "vm.img", "https://host/vm.img", lambda *_: None)

        (request,) = _requests(web)
        assert request["url"] == "https://host/vm.img"
        assert request["headers"]["User-agent"] == "pysandboxes-qemu-provider/1.0"
        assert request["timeout"] == qemu_image.DOWNLOAD_TIMEOUT == 300

    def test_an_unknown_length_is_reported_as_none_and_adds_no_newline(
        self, web: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stderr = io.StringIO()
        monkeypatch.setattr(qemu_image.sys, "stderr", stderr)
        _serve(web, _Response([b"ab"]))
        reports: list[tuple[int, int | None]] = []

        qemu_image.download_image(tmp_path / "vm.img", "https://h/v", lambda done, total: reports.append((done, total)))

        assert reports == [(2, None), (2, None)]
        assert stderr.getvalue() == ""

    def test_a_known_length_ends_the_progress_line(
        self, web: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stderr = io.StringIO()
        monkeypatch.setattr(qemu_image.sys, "stderr", stderr)
        _serve(web, _Response([b"ab"], length="2"))

        qemu_image.download_image(tmp_path / "vm.img", "https://h/v", lambda *_: None)

        assert stderr.getvalue() == "\n"

    def test_a_closed_stderr_does_not_fail_the_final_newline(
        self, web: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Closed:
            def write(self, text: str) -> int:
                raise OSError("closed")

            def flush(self) -> None:
                raise OSError("closed")

        monkeypatch.setattr(qemu_image.sys, "stderr", Closed())
        _serve(web, _Response([b"ab"], length="2"))

        assert qemu_image.download_image(tmp_path / "vm.img", "https://h/v", lambda *_: None).is_file()

    @pytest.mark.parametrize("status", [100, 199, 204, 301, 403, 404, 500])
    def test_a_status_other_than_ok_fails_and_leaves_nothing(
        self, web: list[dict[str, Any]], tmp_path: Path, status: int
    ) -> None:
        _serve(web, _Response([b"x"], status=status))

        with pytest.raises(OSError, match=f"Failed to download https://h/v: Download failed: HTTP {status}"):
            qemu_image.download_image(tmp_path / "vm.img", "https://h/v", lambda *_: None)

        assert list(tmp_path.iterdir()) == []

    def test_a_network_error_is_wrapped_and_the_partial_file_is_removed(
        self, web: list[dict[str, Any]], tmp_path: Path
    ) -> None:
        class Broken(_Response):
            def read(self, size: int) -> bytes:
                if self._chunks:
                    return self._chunks.pop(0)
                raise ConnectionResetError("reset")

        _serve(web, Broken([b"partial"], length="100"))

        with pytest.raises(OSError, match="Failed to download https://h/v: reset") as error:
            qemu_image.download_image(tmp_path / "vm.img", "https://h/v", lambda *_: None)

        assert isinstance(error.value.__cause__, ConnectionResetError)
        assert list(tmp_path.iterdir()) == []

    def test_a_refused_connection_is_wrapped(self, web: list[dict[str, Any]], tmp_path: Path) -> None:
        _serve(web, OSError("refused"))

        with pytest.raises(OSError, match="Failed to download https://h/v: refused"):
            qemu_image.download_image(tmp_path / "vm.img", "https://h/v", lambda *_: None)

    def test_a_callback_that_fails_aborts_the_download(self, web: list[dict[str, Any]], tmp_path: Path) -> None:
        _serve(web, _Response([b"a", b"b"]))

        def stop(done: int, total: int | None) -> None:
            raise KeyboardInterrupt if done > 1 else RuntimeError("stop")

        with pytest.raises(OSError, match="stop"):
            qemu_image.download_image(tmp_path / "vm.img", "https://h/v", stop)

        assert list(tmp_path.iterdir()) == []

    def test_an_existing_image_is_replaced_atomically(self, web: list[dict[str, Any]], tmp_path: Path) -> None:
        (tmp_path / "vm.img").write_bytes(b"old")
        _serve(web, _Response([b"new"]))

        qemu_image.download_image(tmp_path / "vm.img", "https://h/v", lambda *_: None)

        assert (tmp_path / "vm.img").read_bytes() == b"new"


class TestEnsureImage:
    def test_an_existing_image_is_returned_without_any_download(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        image = tmp_path / "vm.img"
        image.write_text("x")
        monkeypatch.setattr(qemu_image, "get_download_url", lambda path: pytest.fail("no lookup expected"))

        assert qemu_image.ensure_image(image) == image

    def test_a_missing_image_is_downloaded_from_the_configured_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[Path, str]] = []
        monkeypatch.setattr(qemu_image, "get_download_url", lambda path: "https://h/v")
        monkeypatch.setattr(qemu_image, "download_image", lambda path, url: calls.append((path, url)))

        assert qemu_image.ensure_image(tmp_path / "vm.img") == tmp_path / "vm.img"
        assert calls == [(tmp_path / "vm.img", "https://h/v")]

    def test_without_a_url_the_error_says_how_to_provide_the_image(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qemu_image, "get_download_url", lambda path: None)

        with pytest.raises(FileNotFoundError) as error:
            qemu_image.ensure_image(tmp_path / "vm.img")

        message = str(error.value)
        assert f"QEMU image not found: {tmp_path / 'vm.img'}" in message
        assert qemu_image.ENV_VM_IMAGE_URL in message and qemu_image.ENV_VM_IMAGE_BASE_URL in message
        assert f"place the image in {tmp_path}" in message


class TestKvm:
    def _kvm(self, monkeypatch: pytest.MonkeyPatch, exists: bool, readable: bool | Exception) -> bool:
        monkeypatch.setattr(
            Path, "exists", lambda self: exists if str(self) == "/dev/kvm" else Path.stat(self) is not None
        )

        def access(path: Any, mode: int) -> bool:
            if isinstance(readable, Exception):
                raise readable
            assert str(path) == "/dev/kvm" and mode == qemu_image.os.R_OK
            return readable

        monkeypatch.setattr(qemu_image.os, "access", access)
        return qemu_image.is_kvm_available()

    def test_kvm_needs_the_device_to_exist_and_be_readable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._kvm(monkeypatch, True, True) is True

    def test_an_unreadable_device_is_not_usable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._kvm(monkeypatch, True, False) is False

    def test_a_missing_device_is_not_usable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._kvm(monkeypatch, False, True) is False

    def test_an_access_error_means_not_usable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._kvm(monkeypatch, True, OSError("denied")) is False
