# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What runs on the host, in the private network namespace, before the gVisor guest exists."""

import shlex
from ipaddress import IPv4Address

from ..all_rules import AllRules
from ..netfilter import rule_to_netfilter
from .slirp4netns_common import SLIRP_DNS, SLIRP_GW


def netfilter_rules(all_rules: AllRules, port: int) -> tuple[str, ...]:
    """Return the ``iptables-restore`` input: default drop, the rules, the daemon port open to the forwarder.

    pre: 0 < port < 65536
    post: __return__[-1] == 'COMMIT' and __return__.count('COMMIT') == 1
    post: ':INPUT DROP [0:0]' in __return__ and ':OUTPUT DROP [0:0]' in __return__
    post: sum(1 for rule in __return__ if f'--dport {port} ' in rule and '-s 10.0.2.2/32' in rule) == 1
    """
    rules = rule_to_netfilter(all_rules.socket_rules, [IPv4Address(SLIRP_DNS)], is_ipv6=False)
    daemon = f"-A INPUT -p tcp -s {SLIRP_GW}/32 --dport {port} -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT"
    index = rules.index("COMMIT")
    return (*rules[:index], daemon, *rules[index:])


_APPEND_GUEST_ARGS = (
    "import json, sys\n"
    "spec_file, fifo, config_copy, *appended = sys.argv[1:]\n"
    "spec = json.load(open(spec_file))\n"
    "spec['process']['args'] += [config_copy if arg == fifo else arg for arg in appended]\n"
    "json.dump(spec, open(spec_file, 'w'))\n"
)


def launcher_script(
    *,
    ready_file: str,
    config_fifo: str,
    config_copy: str,
    rules_file: str,
    spec_file: str,
    python: str,
    ip: str,
    iptables_restore: str,
    runsc_argv: list[str],
) -> str:
    """Return the ``sh -c`` script that holds the guest back until the network is filtered, then starts it.

    It waits for ``ready_file``, which the host creates once slirp4netns is up, brings the loopback up and
    loads the filter, and exits when either fails: the guest never starts unfiltered. The guest cannot open
    a host FIFO, so the config is relayed from ``config_fifo`` to the private file ``config_copy``.

    The arguments ``python-sb`` and ``launch_sandbox`` append to the command line (the user's arguments, then
    the pipe) are the guest's, not ``runsc``'s: they are added to ``process.args`` of ``spec_file``, the pipe
    being replaced by ``config_copy``. Everything else is baked into the script.

    pre: all(p.startswith('/') for p in (ready_file, config_fifo, config_copy, rules_file, spec_file, python, ip))
    pre: iptables_restore.startswith('/')
    pre: len(runsc_argv) > 0 and runsc_argv[0].startswith('/')
    post: __return__.splitlines()[0] == 'umask 077'
    post: __return__.splitlines()[-1].startswith('exec ')
    post: __return__.index('until [ -e') < __return__.index('exit 98') < __return__.rindex('exec ')
    """
    q = shlex.quote
    rewrite = f"{q(python)} -I -c {q(_APPEND_GUEST_ARGS)} {q(spec_file)} {q(config_fifo)} {q(config_copy)}"
    return "\n".join(
        [
            "umask 077",
            f"until [ -e {q(ready_file)} ]; do sleep 0.05; done",
            f"{q(ip)} link set lo up || exit 97",
            f"{q(iptables_restore)} < {q(rules_file)} || exit 98",
            f"cat {q(config_fifo)} > {q(config_copy)} || exit 99",
            f'{rewrite} "$@" || exit 96',
            "exec " + " ".join(q(arg) for arg in runsc_argv),
        ]
    )
