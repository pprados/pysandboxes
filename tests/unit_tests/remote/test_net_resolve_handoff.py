# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`net-resolve=runtime` survives the copy of the rules the server daemon makes for its own context."""

from pysandboxes.all_rules import EmptyRules
from pysandboxes.egress_filter import NameRule
from pysandboxes.remote.sse_server_daemon import SSEServerDaemon
from pysandboxes.sb_types import Envs


def test_the_server_context_keeps_the_mode_and_the_name_rules() -> None:
    names = (NameRule(True, "example.com", ("tcp",), ((443, 443),)),)
    rules = EmptyRules._replace(net_resolve="runtime", name_rules=names)

    server_rules = SSEServerDaemon("token", port=0).update_rules_and_activate(envs=Envs({}), all_rules=rules)

    assert server_rules.net_resolve == "runtime" and server_rules.name_rules == names


def test_the_server_context_of_a_pinned_profile_is_unchanged() -> None:
    server_rules = SSEServerDaemon("token", port=0).update_rules_and_activate(envs=Envs({}), all_rules=EmptyRules)

    assert server_rules.net_resolve == "pinned" and server_rules.name_rules == ()
