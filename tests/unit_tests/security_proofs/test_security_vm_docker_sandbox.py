# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Security proof tests for the VM and container providers (AREA F of the cybedefend audit).

Marked run:    pytest tests/unit_tests/security_proofs/test_security_vm_docker_sandbox.py
Raw run:       pytest --runxfail tests/unit_tests/security_proofs/test_security_vm_docker_sandbox.py
"""

import json
from pathlib import Path
from unittest.mock import patch

from pysandboxes.all_rules import EmptyRules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote import docker_sandbox_daemon as module
from pysandboxes.remote.docker_sandbox_daemon import DockerSandboxSSEDaemon


def test_security_docker_sandbox_control_channel_is_not_published_to_every_interface(tmp_path: Path) -> None:
    """``DockerSandboxSSEDaemon.subprocess_cmd`` (pysandboxes/remote/docker_sandbox_daemon.py) builds the
    ``sbx create shell`` argument list with ``"-p", f"{self.port}:{self.port}"``: Docker's own publish
    syntax for "bind every host interface", since no host address precedes the port pair. Every other VM
    provider keeps its control channel off the host network instead: QEMU's hostfwd is pinned to
    ``127.0.0.1`` (qemu_sse_daemon.py, ``forward = f"tcp:127.0.0.1:{port}-:{port}"``), and gVisor/firejail
    never leave their own private network namespace, so their ``0.0.0.0`` bind is reachable only from
    inside that namespace. docker-sandbox has no such namespace between the published port and the host's
    real interfaces, so the RPC channel -- the whole execution surface of the sandbox, protected only by
    its bearer token, plus an unauthenticated ``/ping`` -- becomes reachable from any machine that can
    reach this host's network, not only from the host itself.
    """
    daemon = DockerSandboxSSEDaemon("token")
    daemon.port = 4321
    rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({}))

    with patch.object(module, "which_command", return_value="/usr/bin/sbx"):
        command, _ = daemon.subprocess_cmd(rules, {}, tmp_path / "pipe", tmp_path)
    create = json.loads(command[-1])["create"]
    published = create[create.index("-p") + 1]

    assert published.startswith("127.0.0.1:"), (
        f"-p {published} publishes the sandbox control channel to every host interface; "
        "it must read 127.0.0.1:<port>:<port> so only the host itself can reach it"
    )
