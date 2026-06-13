# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Regression: ``bwrap`` refuses a symlink as a mount destination, so masks must target real paths."""

from pathlib import Path

from pysandboxes.remote.bwrap_sse_daemon import _ignore_mask_targets


def test_symlink_inside_exposed_tree_masks_its_target(tmp_path: Path) -> None:
    """``ignore=.env`` on ``sub/.env -> ../.env`` must mask the real file, never the link."""
    real = tmp_path / ".env"
    real.write_text("SECRET=1", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / ".env").symlink_to("../.env")

    targets = _ignore_mask_targets(str(tmp_path), [".env", "sub/.env"], [str(tmp_path)])

    assert targets == [str(real)]
    assert not any(Path(t).is_symlink() for t in targets)


def test_symlink_whose_target_name_differs_still_masks_the_target(tmp_path: Path) -> None:
    """The walk only collects the matching name, so the mask must follow the link to its target."""
    secret = tmp_path / "secret_config"
    secret.write_text("SECRET=1", encoding="utf-8")
    (tmp_path / ".env").symlink_to("secret_config")

    targets = _ignore_mask_targets(str(tmp_path), [".env"], [str(tmp_path)])

    assert targets == [str(secret)]


def test_symlink_leaving_the_exposed_tree_is_not_masked(tmp_path: Path) -> None:
    """A link resolving outside the exposed tree is already invisible; binding over it would fail."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".env").write_text("SECRET=1", encoding="utf-8")
    exposed = tmp_path / "exposed"
    exposed.mkdir()
    (exposed / ".env").symlink_to("../outside/.env")

    targets = _ignore_mask_targets(str(exposed), [".env"], [str(exposed)])

    assert targets == []


def test_plain_file_is_masked_in_place(tmp_path: Path) -> None:
    """Without symlinks, the ignore path itself is the mask destination."""
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")

    targets = _ignore_mask_targets(str(tmp_path), [".env"], [str(tmp_path)])

    assert targets == [str(tmp_path / ".env")]


def test_missing_ignore_path_is_skipped(tmp_path: Path) -> None:
    """Nothing to mask when the resolved path does not exist."""
    targets = _ignore_mask_targets(str(tmp_path), ["absent.env"], [str(tmp_path)])

    assert targets == []
