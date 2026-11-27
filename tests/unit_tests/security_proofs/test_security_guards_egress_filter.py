# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Security proof tests for the runtime DNS egress filter (AREA C of the cybedefend audit).

Marked run:    pytest tests/unit_tests/security_proofs/test_security_guards_egress_filter.py
Raw run:       pytest --runxfail tests/unit_tests/security_proofs/test_security_guards_egress_filter.py
"""

import asyncio

from pysandboxes.egress_filter import FilteringResolver, LearnedTable
from tests.unit_tests.test_egress_filter_resolver import RULES, Clock, Upstream, a_record, ask_udp, query, run


class _FailingRevokeEnforcer:
    """An enforcer whose ``allow`` always succeeds and whose ``revoke`` always fails,
    like a single transient ``nft``/``iptables`` error would."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.revoke_calls = 0

    def allow(self, ip: object, rule: object, ttl: int) -> None:
        self.events.append(("allow", str(ip)))

    def revoke(self, ip: object, rule: object) -> None:
        self.revoke_calls += 1
        raise OSError("nft delete rule failed")


def test_security_a_failed_revoke_is_retried_instead_of_being_forgotten() -> None:
    """``FilteringResolver._reap`` (``pysandboxes/egress_filter.py``) asks ``LearnedTable.expired()`` for the
    keys whose TTL is over, and that call deletes them from the table's own bookkeeping before the enforcer is
    ever asked to revoke them. When ``enforcer.revoke()`` raises -- a single transient firewall-tool error --
    the exception is only logged (``except Exception: logger.warning(...)``): the key is already gone, so no
    later reap cycle retries it. The address that was opened in the kernel filter for the name's TTL
    (``wiki/weaknesses.md``'s ``net-resolve=runtime``, 60 s to 1 h) then stays reachable from the sandbox for
    the rest of the run, with no rule and no further attempt to close it -- a wider, silent, permanent
    extension of network access that the profile never granted.
    """
    clock = Clock()
    enforcer = _FailingRevokeEnforcer()
    table = LearnedTable(clock)
    resolver = FilteringResolver(RULES, enforcer, Upstream([a_record("192.0.2.7", 60)]), table, reap_interval=0.02)

    async def scenario(_: FilteringResolver, port: int) -> None:
        await ask_udp(port, query("api.example.com"))
        await asyncio.sleep(0.1)
        assert enforcer.events == [("allow", "192.0.2.7")]
        clock.now += 61
        # Several reap cycles elapse after the TTL is over: a real transient failure
        # is not a one-shot event either, and the guarantee is that the address ends
        # up closed, not that the first attempt alone decides it forever.
        for _cycle in range(8):
            await asyncio.sleep(0.05)

    run(scenario, resolver)

    assert enforcer.revoke_calls >= 1  # the reaper did try once
    # Guarantee under test: an expired address is retried until it is actually revoked,
    # never abandoned after a single failed attempt.
    assert enforcer.revoke_calls > 1
