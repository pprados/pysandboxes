# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Security proof tests for the remote RPC channel (AREA A of the cybedefend audit).

Marked run:    pytest tests/unit_tests/security_proofs/test_security_rpc_channel.py
Raw run:       pytest --runxfail tests/unit_tests/security_proofs/test_security_rpc_channel.py
"""

import asyncio
import http.server
import threading
from typing import Any, ClassVar

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote.sse_server_daemon import SSEServerDaemon


class _CapturingHandler(http.server.BaseHTTPRequestHandler):
    """Stands for an impostor already bound on the sandbox's port: answers /ping, then
    records whatever the host sends to /rpc instead of running anything."""

    captured: ClassVar[dict[str, Any]] = {}

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        if self.path == "/ping":
            body = b'{"message": "OK"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        _CapturingHandler.captured["authorization"] = self.headers.get("Authorization")
        _CapturingHandler.captured["body"] = body
        # No real sandbox ever answers from here: refusing the request is enough,
        # the secret was already read off the wire by the time this runs.
        self.send_response(500)
        self.end_headers()

    def log_message(self, *_args: Any) -> None:  # silence http.server's own access log
        return


def test_security_the_bearer_token_is_sent_to_whatever_answers_the_sandbox_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``BaseSSESandbox.async_call_in_sandbox`` (``pysandboxes/remote/base_sse_daemon.py``) authenticates the
    *application* to the sandbox (the ``Authorization: Bearer <token>`` header), but never authenticates the
    far end: it sends the token and the call's serialized arguments to whatever process answers 200 on
    ``/ping`` at the chosen ``127.0.0.1:<port>``, with no check that it is the child this process itself
    started.

    ``client_subprocess_sse_daemon.find_free_port()`` picks a port by binding it, reading the number back,
    and closing the socket again before the real subprocess is even launched; the chosen port is then free for
    any other local process to bind in the window before the real child's own listener claims it. The
    ``remote-endpoint=unix`` path the same module offers is immune by construction, because the parent binds
    the listening socket itself and hands the live descriptor down to the child -- proof the project already
    treats this exact race as worth closing, for the providers that can use it. The TCP fallback
    (``remote-endpoint=tcp``, a fixed ``port=``, a provider that cannot hand a socket down, or any platform
    other than Linux/macOS, Windows included) keeps the race: whoever occupies the port first receives the
    full token and the pickled call payload, unauthenticated, and can answer with a crafted result or
    exception of its own choosing.

    This test does not attempt to win the race; it fixes the end state a winner reaches (a process already
    listening on the port the client is about to call) and shows the client hands over the secret anyway.
    """
    _CapturingHandler.captured.clear()
    server = http.server.HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    secret_token = "the-applications-secret-bearer-token"
    monkeypatch.setattr("pysandboxes._os_sandbox.get_token", lambda: secret_token)

    daemon = SSEServerDaemon("unused-server-side-token", port=port)
    daemon.max_connect_retry = 1
    daemon._accept_incoming = True

    async def func() -> int:
        raise AssertionError("must not run: the call never reaches a real sandbox in this test")

    try:
        with pytest.raises(Exception):  # noqa: B017 - the impostor's 500 ends the call one way or another
            asyncio.run(daemon.async_call_in_sandbox(func, False))
    finally:
        server.shutdown()
        thread.join(timeout=2)

    # Guarantee under test: the host never discloses its sandbox token to a peer it has not verified.
    assert _CapturingHandler.captured.get("authorization") != f"Bearer {secret_token}", (
        "the host sent its bearer token (and the call's serialized arguments, in "
        f"{_CapturingHandler.captured.get('body')!r}) to a process on 127.0.0.1 that was never shown to be "
        "the sandbox it started."
    )
