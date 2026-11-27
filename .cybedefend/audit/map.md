# Audit map: PySandboxes

Repository: Python sandbox framework (library + `python-sb` CLI + per-provider daemons). Reviewed in 8 areas (A to H) by separate reviewers, each reading its files and the project's own audit pages (`SECURITY.md`, `wiki/weaknesses.md`, `wiki/audit-*.md`).

## Roles

No account exists. The parties are: the trusted host application / operator who writes the rule file and starts the sandbox; the sandboxed program (untrusted, the party the product confines); another local user or process on the host; a peer on the same bridge or network; a maintainer running scripts.

## Guarantees

- Default deny-all: a path, host, environment variable or sensitive API is allowed only through an explicit rule.
- Sandboxed code never changes the rules that govern it (no write to a loaded config file, no rule added when `learn=false`).
- The control channel between host and child is reachable only by the host that started it, and only with the per-run token.
- Data from the child is never trusted on the host (restricted unpickling of results).
- A provider that is unavailable refuses to start; it never runs with weaker isolation silently.
- Code evaluated under a named `eval-*` profile never exceeds that profile's rules.

Families: rights (self-granted permissions), input trusted too early, configuration in code, checks that fail open, dangerous calls (argv, profile strings), data that leaves, infrastructure. Surfaces: native-and-local, infrastructure. Flows: sandbox start (rules loaded, provider chosen, daemon launched, token handed over, call made, result returned); learning mode (observe, write rule file).

## Area A: remote host/child channel

| Entry point | Who may call it | Reads / changes | The check that enforces it (file:line) | Verdict |
|---|---|---|---|---|
| `GET /ping` | anyone who reaches the port | liveness only | none needed, constant answer, `sse_server_daemon.py:269` | ok: constant `{"message":"OK"}`, nothing to protect |
| `POST /rpc` authentication | holder of the bearer token | gates every call | `hmac.compare_digest`, `sse_server_daemon.py:287-290`; token `uuid4`, `_os_sandbox.py:326`, never in argv, env or logs | ok |
| `POST /rpc` function dispatch | token holder | `import_module` + `getattr` under `user_code()` | `sse_server_daemon.py:151-153`, Python guards still apply | ok: by design, the token is the sole gate |
| `POST /rpc` arguments decode | host to child only | raw `pickle.loads` (`from_b85`) | `sse_server_daemon.py:298-299`, repo-wide sweep shows no parent-side raw load of child bytes | ok |
| Result channel child to parent | the running sandboxed function | restricted unpickler + predicate | `base_sse_daemon.py:277-281`, `tools.py:774-791` | ok: documented residual, `wiki/transport-unpickle-guard.md` |
| Exception channel child to parent | the running sandboxed function | rebuild from descriptor | `wiki/transport-unpickle-guard.md:52-60` | ok: documented residual |
| Traceback shape check | child output | bounds and cycle check | `base_sse_daemon.py:66-89` | ok |
| Config bootstrap by named pipe | trusted parent only | `pickle.loads` of `DaemonParameters` | FIFO 0600 in a private temp dir, `client_subprocess_sse_daemon.py:176,557,249` | ok |
| Config bootstrap `--_config-on-stdin` | smolvm and docker launchers | same | `config_stream.py:42`, single local writer | ok |
| `--_shared-socket` | appcontainer launcher only | `socket.fromshare()` | `main_sandbox.py:424-425`, private per-run path | ok |
| `config_writer` callback | VM path | no-op in every real use | `qemu_sse_daemon.py:1567`, `python_sb.py:258` | ok |
| Unix-socket endpoint mode | host | parent binds, hands the live fd down | `client_subprocess_sse_daemon.py:573-574,646,665` | ok |
| TCP endpoint mode (fallback, Windows, fixed `port=`) | a local process that wins the port race | `find_free_port` binds, closes, reuses later | `client_subprocess_sse_daemon.py:263-282` | ok: fixed, the peer proves it holds the token before it is sent, `base_sse_daemon.py` `_verify_sandbox_peer` |
| `main_shutdown.daemon_shutdown` | token holder | stops the daemon | same gate as any `/rpc` function | ok |
| `python-sb` / `main_sandbox` argument parsing | the local operator | builds the child command | `parse_cpython_args.py`, `main_sandbox.py:392-403` | ok |
| `python_in_sb.py` dispatch | the local operator | runs under armed guards | `_before_user_code` | ok |
| Host rule `net=ALLOW\|TCP\|*\|{port}\|IN` | the host, for isolated providers | opens the daemon port inbound from any source | `client_subprocess_sse_daemon.py:566` | lead: inbound source `*` not narrowed to the parent |

## Area B: configuration and public API

| Entry point | Who may call it | Reads / changes | The check that enforces it (file:line) | Verdict |
|---|---|---|---|---|
| `@sandbox` decorator | host application | marshals a call across the boundary | generator refusal, `sandboxes_api.py:157` | ok |
| `sandboxes()` / `run()` | host application | loads config, starts daemon, arms guards | `_refuse_locked_extra_rules`, `sandboxes_api.py:59` | ok |
| `load_and_parse_config` / `parse_config` | whoever places a rule file | builds `AllRules` | unknown-key catch-all `py_sandbox.py:331` | ok: fixed, the error shows the rule as written, `py_sandbox.py` `as_written` |
| `_parse_include` (`include "file"`) | whoever controls a path an include names | merges another file into the profile | protected set built only from files that exist, `py_sandbox.py:198,354` | ok: fixed, a missing include is protected too, `py_sandbox.py` `_parse_include` |
| `guard_provider.parse_rules` | operator config | provider, guard switch, learning, lock | conflicting `os-sandbox=` raises, `guard_provider.py:258`; lock `:17` | ok |
| `substitute_config_env_vars` / `resolve_env_variables` | operator config | resolves `${VAR}` before parsing | no escaping before error messages | ok: fixed, the error shows the rule as written, `py_sandbox.py` `as_written` |
| `_os_sandbox.py` registry, `start_daemon`, `check_provider_available` | parsed `os_sandbox` value | selects and launches the daemon | unavailable provider raises `ValueError`, `_os_sandbox.py:138` | ok |
| `default_os_sandbox()` | nobody, fresh template only | fallback to `subprocess` for a first template | logged, `_os_sandbox.py:152` | ok |
| `learning.py` | sandboxed code while learning is on | records accesses, rewrites the rule file | observe-not-enforce by design, `README.md:112` | ok: documented, `wiki/weaknesses.md` |
| `python-sb` CLI (`python_sb.py::main`) | its operator | launches the child | lock checks `python_sb.py:156,180` | ok |
| `lifecycle.py` | framework code | armed state | pytest-only reset guard, `lifecycle.py:79` | ok: documented |
| `base_daemon.py` | framework code | daemon base | `FakeDaemon.call_in_sandbox` raises, `base_daemon.py:228` | ok |
| `immutable_dict.py`, `sb_types.py`, `e.py`, `main_logger.py`, `templates/` | framework code | data and formatting | no input boundary | not examined: pure data and formatting, no entry point |

## Area C: Python guards

| Entry point | Who may call it | Reads / changes | The check that enforces it (file:line) | Verdict |
|---|---|---|---|---|
| `open`, `io.open`, `io.FileIO`, `os.open` | sandboxed code | file access | realpath-resolved rules, `guard_files.py:943-998,1303-1340,1789-1886` | ok |
| `os.stat`, `lstat`, `access`, chmod, chown, mkdir, rename, link, unlink, listdir, readlink, `dir_fd`, `/proc/self/fd` | sandboxed code | file metadata and changes | `guard_files.py:705-930,1153-1668` | ok |
| `os.scandir()` entry methods (`stat`, `is_dir`, `is_file`, `inode`) | sandboxed code | metadata through a symlink | `_DirEntry.__getattr__`, `guard_files.py:95-119` | ok: fixed, `_DirEntry.stat/is_dir/is_file` apply the path rules, `guard_files.py` |
| `shutil.copytree` callbacks | sandboxed code | copies | `guard_files.py:1110-1150` | ok |
| `os`/`posix`/`nt` twin aliasing | sandboxed code | alias bypass | `_twin_rules`, `guard_files.py:2055-2089` | ok |
| `socket`/`_socket` connect, bind, listen, sendto, sendmsg, `getaddrinfo` | sandboxed code | network | `guard_socket.py:1669-1740` | ok |
| `sys.modules` cached module read, `__subclasses__`, closures, `pickle.Unpickler`, `ctypes.pythonapi` | sandboxed code | Python-layer escapes | out of scope per `SECURITY.md` | ok: documented, `wiki/weaknesses.md` |
| `spec_from_file_location`, `zipimport`, `marshal.loads`, ambient gateway walk | sandboxed code | code loading | fixed 2026-11-16, regression-tested | ok: documented |
| `guard_api.SENSITIVE_API` (152 functions) | sandboxed code | sensitive calls | `guard_api.py:31-307` | ok |
| `os.environ`, `getenv`, `putenv` | sandboxed code | environment | applied at spawn, `guard_envs.py:521-534` | ok: documented by design |
| `net-resolve=runtime` reap and revoke cycle | the filtering resolver | opens and closes addresses | `egress_filter.py:99-105,344-351` | ok: fixed, a failed revoke is retried, `egress_filter.py` `LearnedTable.retry` |
| `netfilter.py` DNS port 53 passthrough | sandboxed code | DNS | `wiki/weaknesses.md` | ok: documented |
| `private_loop.py` background loop | framework code | async tasks | broad except is resiliency | ok |
| `guard_provider.py`, `override_compat.py`, `guard_wraps.py` | framework code | wrappers | no extra logic | ok |
| `guard_import.py` import rules | sandboxed code | imports | import hook rules | ok |

## Area D: dynamic code layer

| Entry point | Who may call it | Reads / changes | The check that enforces it (file:line) | Verdict |
|---|---|---|---|---|
| `builtins.eval` / `exec` wrapper (`_wrap_eval_like`) | code holding `eval-call` | runs source in-process | `guard_eval.py:966-1032`, rules resolved at `:1004` | ok: fixed, nested calls keep the enclosing profile, `guard_eval.py` `_rules_for_nested_call` |
| `builtins.compile` wrapper | same | validates or returns a tree | `guard_eval.py:1035-1074`, `:1052` | ok: fixed, nested calls keep the enclosing profile, `guard_eval.py` `_rules_for_nested_call` |
| `marshal.loads` / `load` wrapper | code with the dynamic-code grant | code object | `guard_eval.py:1077-1109`, deny by default | ok: documented fix |
| `string.Formatter.get_field` wrapper | any Formatter user | field walk | `guard_eval.py:1112-1134` | ok |
| Ambient gateway tables | library call sites | decides library vs application code | `guard_eval.py:656-891`, self-testing | ok: documented |
| `eval_transform._Validator` | evaluated source | static refusal | `eval_transform.py:158-339` | ok |
| `eval_transform._Injector` | evaluated source | runtime enforcement injection | `eval_transform.py:417-544` | ok |
| `eval_runtime` attribute gate | evaluated code | every attribute read | `eval_runtime.py:215-253,385-411` | ok: nested-object residual documented |
| `__sb_binop__` allocation checks | evaluated code | DoS guard | `eval_runtime.py:611-669` | ok |
| `str.format` / `format_map` field validation | evaluated code | field walk | `eval_runtime.py:282-412` | ok |
| `eval_rules.parse_rules` | config author | per-profile rules | `eval_rules.py:61-71,346-492` | ok |
| Budget and timeout watchdog | evaluated code | loop, recursion, wall clock | `guard_eval.py:526-598`, `eval_runtime.py:152-213` | ok: blocking C call residual documented |

## Area E: Linux OS providers and network plumbing

| Entry point | Who may call it | Reads / changes | The check that enforces it (file:line) | Verdict |
|---|---|---|---|---|
| `LandlockSSEDaemon.unavailable_reason` | provider selection | refuses an old ABI | `landlock_daemon.py:451` | ok |
| `update_rules_and_activate` / `_apply_landlock` | daemon | applies Landlock | fails closed on error, `landlock_daemon.py:474,242` | ok |
| `_collect_landlock_paths` | daemon | paths granted | cwd only through a rule, `landlock_daemon.py:370,407` | ok: `/dev/shm` documented |
| `BWrapSSEDaemon._bwrap_args` | daemon | bwrap command line | no automatic bind of cwd, `bwrap_sse_daemon.py:486` | ok |
| `_filtered_network` / `_apply_netfilter_from_host` | daemon | network filter | raises when tools are missing, `bwrap_sse_daemon.py:336,120` | ok |
| `bwrap.share-net` truthiness | operator | shares host network | `bwrap_sse_daemon.py:281` | ok: documented, `wiki/bwrap.md:103` |
| `FireJailSSEDaemon._firejail_args` | daemon | firejail command line | `firejail_sse_daemon.py:495-514` | ok: `restricted-network yes` opt-out documented |
| `UnshareSSEDaemon._prepare_unshare_config` mounts | daemon | mounts from rules | `unshare_sse_daemon.py:240` | ok |
| `unshare_setup.main` step F "Mount current directory" | daemon | binds cwd read-write with no rule | `unshare_setup.py:354-355` | ok: fixed, the working directory is mounted read-only, `unshare_setup.py:355` |
| `unshare_setup.main` chmod 1777 on chroot `/tmp` | daemon | tmpfs mode | fresh tmpfs in a private namespace, `unshare_setup.py:345` | ok |
| `FilteringResolver.answer` | resolver | opens every address of an answer | `egress_filter.py:308` | ok: documented, `wiki/weaknesses.md:19` |
| `guard_socket.parse_name_rules` | rule parsing | empty port semantics | `guard_socket.py:603-620` | ok: by design |
| `NetnsIptablesEnforcer` allow and revoke | resolver | iptables argv | typed arguments, `netns_enforcer.py:72-90` | ok |
| `slirp4netns_common` temp files and API socket | daemon | temp files | `mkstemp`, `slirp4netns_common.py:312-333` | ok |
| `RuntimeDnsSession.start` / `attach` | daemon | runtime DNS | fails closed, `runtime_dns.py:157,183` | ok |
| `ipv6_route.wait_default_route` | daemon | waits for a route | timeout returns False, `ipv6_route.py:27` | ok |
| `UnshareSSEDaemon` /etc/hosts building from raw rule text | operator rules | hosts file lines | `unshare_sse_daemon.py:294-316` | lead: host field with newline or pipe not validated |
| `FireJailSSEDaemon` runtime resolver bound to the bridge gateway | peers on the bridge | DNS answers | `firejail_sse_daemon.py:555-559` | lead: resolver reachable by any peer on the bridge |

## Area F: VM and container providers

| Entry point | Who may call it | Reads / changes | The check that enforces it (file:line) | Verdict |
|---|---|---|---|---|
| `qemu_sse_daemon._machine_command` | operator rules | QEMU argv | comma escaping, `qemu_sse_daemon.py:970-977`; memory regex `qemu_image.py:25,39` | ok |
| `qemu_setup._bootstrap_script_content` | operator rules | guest boot script | `shlex.quote`, `qemu_setup.py:285-287` | ok |
| `qemu_guest_console_io` | the sandboxed guest | host parses guest output | sentinel match only, `qemu_guest_console_io.py:287-290` | ok |
| `guest_learned.handle` | a process in the guest network namespace | runs `iptables -A/-D LEARNED` | verb and chain only, `guest_learned.py:54-58`; unreachable under default DROP, `netfilter.py:104-109`; shares the daemon token with `main_sandbox.py:441-445` | lead: remaining iptables arguments not validated, reachability to settle |
| `qemu_image.ensure_image` / `download_image` | operator URL | downloads an image | checksum required, `qemu_image.py:644-660,505,274` | ok: residual documented |
| `qemu_microvm_boot.ensure_microvm_boot_artifacts` | verified image | extracts kernel and initrd | fixed target paths, `qemu_microvm_boot.py:105-109` | ok |
| `gvisor_bundle.build_oci_spec` / `gvisor_launch.launcher_script` | operator rules | OCI spec and launcher | `gvisor_bundle.py:167-171`, `gvisor_launch.py:91-105` | ok |
| `gvisor_sse_daemon._sse_bind_host` | guest | binds 0.0.0.0 in a private namespace | `gvisor_launch.py:13-24` | ok |
| `smolvm_root.init_script` / `smolvm_sse_daemon.subprocess_cmd` | operator rules | guest init, share flags | `shlex.quote`, `smolvm_sse_daemon.py:217-259` | ok |
| `docker_sandbox_launcher.main` / `_setup` | host | `sbx` orchestration | list-form calls, no shell | ok |
| `docker_sandbox_daemon.subprocess_cmd` port publish | anyone who reaches the host network | publishes the control channel | none, `-p {port}:{port}`, `docker_sandbox_daemon.py:301` | ok: fixed, published on `127.0.0.1`, `docker_sandbox_daemon.py:301` |
| `docker_sandbox_rules.sbx_rules` | operator rules | `sbx policy` arguments | no shell | ok: documented residuals |

## Area G: Windows, macOS, scripts

| Entry point | Who may call it | Reads / changes | The check that enforces it (file:line) | Verdict |
|---|---|---|---|---|
| `AppContainerSSEDaemon.subprocess_cmd` | sandbox starter | ACL plan | `build_acl_plan`, `appcontainer_acl.py:48,83` | ok |
| `appcontainer_launcher.run()` | the daemon only | profile, ACLs, child | ACL scoped to the run SID, `appcontainer_acl.py:132-167`; token `sse_server_daemon.py:288` | ok |
| `apply_acl` / `mask_acl` / `_deny_access` | the launcher | DACL writes | `_verified_handle` re-checks the final path, `appcontainer_acl.py:314-357` | ok |
| `begin_run` / `finish_run` / `_reap_stale_runs_locked` | the launcher | per-run grants, profile deletion | `appcontainer_acl.py:704-826` | lead: a killed launcher leaves grants until the next launch |
| `win_job` kill-on-close job | the launcher | job limits | `win_job.py:76` | ok: no memory limit, documented in `wiki/os-providers.md` |
| `win_window` service window access | the launcher | window station rights | `win_window.py:171` | ok |
| `SandboxExecSSEDaemon._build_profile` | sandbox starter | Seatbelt profile text | `_sbpl_string`, `_glob_regex`, `sandbox_exec_daemon.py:42-136`, 8 hostile inputs tried | ok |
| `sandbox_exec_daemon._network_rules` | sandbox starter | widens host-scoped rules | `SECURITY.md`, `wiki/weaknesses.md` | ok: documented |
| `scripts/*.py`, `research/md2latex.py` | the maintainer | benchmark, compress, mutate, build | list-form subprocess, no shell | not examined: operator-run tooling crosses no boundary |

## Area H: infrastructure and samples

| Entry point | Who may call it | Reads / changes | The check that enforces it (file:line) | Verdict |
|---|---|---|---|---|
| `.github/workflows/api-docs.yml` | maintainers (push, dispatch) | docs deploy | scoped `pages` and `id-token` on the deploy job | ok |
| `.github/workflows/containers.yml` | dispatch, call | container tests | no external trigger | ok |
| `.github/workflows/crewai-macos.yml` | push, dispatch | macOS sample test | no secrets | ok |
| `.github/workflows/cross-os.yml` | dispatch, call | cross-OS tests | matrix of hosted runners | ok |
| `.github/workflows/full-gate.yml` | dispatch, call | orchestrates | local `uses` only | ok |
| `.github/workflows/images-refresh.yml` | schedule, dispatch | dispatches `images.yml` | no registry credential | ok |
| `.github/workflows/images.yml` | dispatch | image push | tag signature and ancestry check, environment gate | ok |
| `.github/workflows/integration.yml` | dispatch, call | integration tests | gVisor key goes to an apt keyring | ok |
| `.github/workflows/lint.yml` | pull_request | lint | `pull_request`, read-only token on forks | ok: missing `permissions:` kept by triage |
| `.github/workflows/nightly-trigger.yml` | schedule, dispatch | dispatches the full gate | `github.token` only | ok |
| `.github/workflows/release.yml` | tag push | publish | signed tag check, Trusted Publishing, environments | ok |
| `.github/workflows/samples.yml` | dispatch, call | samples tests | same key pattern as integration | ok |
| `.github/workflows/test.yml` | pull_request | tests | `pull_request`, read-only token on forks | ok: missing `permissions:` kept by triage |
| `.github/workflows/wiki.yml` | push on wiki paths | wiki sync | `GITHUB_TOKEN` masked | ok |
| `Dockerfile` and `Dockerfile-bwrap`, `-landlock`, `-qemu`, `-qemu-microvm`, `-unshare` | build | images | local base image, no network fetch | ok: root user kept by triage |
| `Dockerfile-gvisor` | build | image | apt `signed-by` key | ok |
| `Dockerfile-smolvm` | build | image | pinned `sha256sum -c` | ok |
| `Dockerfile-smolvm-guest` | build | guest image | pinned base image | ok |
| `Dockerfile-docker-sandbox` | build | image | `pip install uv` without a version, line 13 | lead: uv not pinned, hardening only, kept in the map |
| `.oss-scanner/Dockerfile` | build | scanner image | `uv:latest`, line 10, no workflow uses it | lead: mutable tag, hardening only, kept in the map |
| `samples/agno-demo`, `autogen-demo`, `crewai-demo`, `google-adk-demo`, `langchain-demo`, `openai-agents-sdk-demo`, `pydantic-ai-demo`, `smolagents-demo`, `strands-agents-demo` | demo user | `eval` and fetch tools | tools run inside `with sandboxes(...)` or `pysandboxes.run(...)` | ok: runs under the sandbox |
| `samples/langgraph-demo/cli.py` | demo user | chat, ask, calc, fetch | `pysandboxes.run(...)`, `cli.py:35,54,67,80` | ok |
| `samples/mcp-client-demo/main.py` | demo user | MCP client | no dangerous call, tools run on the server | ok |
| `samples/mcp-server-demo/mcp_server/main.py:126` | MCP client | `eval` | `@sandbox`, run inside `with sandboxes(...)`, `main.py:167` | ok |
| `samples/quick-demo/app/demo.py` | demo user | deliberate unsandboxed step | `SECURITY.md` excludes `samples/` | ok: documented, pedagogical |
