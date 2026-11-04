# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The OCI spec handed to runsc is the whole filesystem, environment and privilege boundary of the guest."""

from typing import Any

from pysandboxes.remote.gvisor_bundle import build_oci_spec

_EMPTY_FILE = "/run/empty-file"


def _spec(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = dict(
        rootfs="/run/rootfs",
        args=["python", "-m", "pysandboxes.remote.main_sandbox"],
        env={"PATH": "/usr/bin"},
        mounts_ro=[],
        mounts_rw=[],
        masks=[],
        empty_file=_EMPTY_FILE,
        cwd="/work",
    )
    params.update(overrides)
    return build_oci_spec(**params)


def _mount(spec: dict[str, Any], destination: str) -> dict[str, Any]:
    found = [m for m in spec["mounts"] if m["destination"] == destination]
    assert len(found) == 1, f"expected one mount on {destination}, got {found}"
    return found[0]


def test_the_root_filesystem_is_read_only() -> None:
    assert _spec()["root"] == {"path": "/run/rootfs", "readonly": True}


def test_the_guest_holds_no_capability_and_cannot_gain_one() -> None:
    process = _spec()["process"]

    assert process["noNewPrivileges"] is True
    assert all(caps == [] for caps in process["capabilities"].values())


def test_the_environment_is_exactly_the_one_given() -> None:
    process = _spec(env={"PATH": "/usr/bin", "ALLOWED": "yes"})["process"]

    assert sorted(process["env"]) == ["ALLOWED=yes", "PATH=/usr/bin"]


def test_the_command_and_working_directory_are_carried() -> None:
    process = _spec(args=["echo", "hi"], cwd="/work")["process"]

    assert process["args"] == ["echo", "hi"]
    assert process["cwd"] == "/work"


def test_a_read_only_exposure_is_a_read_only_bind() -> None:
    mount = _mount(_spec(mounts_ro=["/data"]), "/data")

    assert mount["type"] == "bind"
    assert mount["source"] == "/data"
    assert "ro" in mount["options"]
    assert "rw" not in mount["options"]


def test_a_read_write_exposure_is_a_read_write_bind() -> None:
    mount = _mount(_spec(mounts_rw=["/scratch"]), "/scratch")

    assert "rw" in mount["options"]
    assert "ro" not in mount["options"]


def test_a_path_in_both_lists_is_read_only() -> None:
    mount = _mount(_spec(mounts_ro=["/both"], mounts_rw=["/both"]), "/both")

    assert "ro" in mount["options"], "the narrower right wins when a path is exposed twice"


def test_a_masked_file_is_replaced_by_an_empty_read_only_file() -> None:
    spec = _spec(mounts_rw=["/proj"], masks=[("/proj/.env", False)])

    mount = _mount(spec, "/proj/.env")

    assert mount["type"] == "bind"
    assert mount["source"] == _EMPTY_FILE
    assert "ro" in mount["options"]


def test_a_masked_directory_is_replaced_by_an_empty_tmpfs() -> None:
    spec = _spec(mounts_rw=["/proj"], masks=[("/proj/secrets", True)])

    assert _mount(spec, "/proj/secrets")["type"] == "tmpfs"


def test_a_mask_comes_after_the_exposure_that_contains_it() -> None:
    spec = _spec(mounts_rw=["/proj"], masks=[("/proj/.env", False)])
    order = [m["destination"] for m in spec["mounts"]]

    assert order.index("/proj") < order.index("/proj/.env")


def test_the_guest_has_a_private_writable_tmp_that_the_host_never_sees() -> None:
    mount = _mount(_spec(), "/tmp")

    assert mount["type"] == "tmpfs"
    assert "ro" not in mount["options"]


def test_proc_is_mounted_unless_disabled() -> None:
    assert _mount(_spec(), "/proc")["type"] == "proc"
    assert all(m["destination"] != "/proc" for m in _spec(mount_proc=False)["mounts"])


def test_the_guest_gets_the_network_of_its_launcher_not_a_new_one() -> None:
    kinds = {ns["type"] for ns in _spec()["linux"]["namespaces"]}

    assert "network" not in kinds, "the private netns is created by the launcher, which filters it first"
    assert {"pid", "ipc", "uts", "mount"} <= kinds
