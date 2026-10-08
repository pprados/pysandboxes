# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""``python -m pysandboxes.remote.qemu_fetch_image``: the exit code of the process is the one ``main()`` returns."""

import runpy
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote import qemu_image

_MODULE = "pysandboxes.remote.qemu_fetch_image"

# runpy executes the module code afresh; it only warns that an earlier test already imported it.
pytestmark = pytest.mark.filterwarnings(f"ignore:'{_MODULE}' found in sys.modules:RuntimeWarning")


@pytest.fixture
def image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "images" / "default.qcow2"
    monkeypatch.setattr(qemu_image, "get_vm_images_dir", lambda: path.parent)
    monkeypatch.setattr(qemu_image, "get_default_image_path", lambda: path)
    return path


def test_running_the_module_exits_with_the_failure_code_of_main(
    image: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_url(path: Path) -> None:
        raise FileNotFoundError(f"{path} is missing")

    monkeypatch.setattr(qemu_image, "ensure_image", no_url)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module(_MODULE, run_name="__main__")

    assert exit_info.value.code == 1
    assert f"{image} is missing" in capsys.readouterr().out


def test_running_the_module_exits_with_zero_when_the_image_is_present(
    image: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image.parent.mkdir()
    image.write_bytes(b"qcow")

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module(_MODULE, run_name="__main__")

    assert exit_info.value.code == 0
    assert "Image already present." in capsys.readouterr().out
