# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import asyncio
import logging
import os
import subprocess
import sys
import tempfile
import uuid
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping, TextIO, cast

from ._os_sandbox import providers_factory
from .all_rules import AllRules
from .base_daemon import BaseDaemon
from .config import DEBUG
from .e import ConfigSyntaxError
from .guard_provider import learn_lock
from .main_logger import config_log, format_ruleref
from .py_sandbox import load_and_parse_config
from .remote.client_subprocess_sse_daemon import (
    BaseSubProcessDaemon,
    find_free_port,
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from .remote.daemon_parameters import DaemonParameters
from .remote.none_daemon import NoneDaemon
from .remote.parse_cpython_args import parse_python_cmd_line
from .remote.python_in_sb import convert_extra_rules
from .remote.qemu_guest_console_io import GUEST_STDERR_FILE, GuestStderrTail
from .remote.vm_sse_daemon import VMSSEDaemon
from .sb_types import Envs
from .tools import Environ, exit_status, shell_status

# Default console size when not a TTY (e.g. CI, pipes)
_DEFAULT_COLUMNS = 80
_DEFAULT_LINES = 24


def _get_terminal_size() -> tuple[int, int]:
    """Return (columns, lines) from the current terminal, or defaults when not a TTY."""
    try:
        size = os.get_terminal_size()
        return (size.columns, size.lines)
    except OSError:
        pass
    try:
        cols = int(os.environ.get("COLUMNS", str(_DEFAULT_COLUMNS)))
        lines = int(os.environ.get("LINES", str(_DEFAULT_LINES)))
        return (max(1, cols), max(1, lines))
    except (ValueError, TypeError):
        return (_DEFAULT_COLUMNS, _DEFAULT_LINES)


logger = logging.getLogger(__name__)

QEMU_CONSOLE_LOG_NAME = ".pysandbox-qemu-console.log"


def _open_qemu_console_log() -> tuple[TextIO | None, Path | None]:
    """Open the boot console log next to the run, or failing that under the temp dir.

    A diagnostic aid must not be able to kill the run it was turned on to diagnose.
    The container suite runs the docker rows before the podman ones over the same
    checkout: docker runs as real root and leaves this file owned by uid 0, then
    rootless podman maps to another uid and cannot reopen it for writing. So
    ``qemu.show_boot_console=true`` raised PermissionError before the VM had even
    started -- on the one option reached for when a QEMU run goes wrong. The temp
    dir is the fallback rather than the run dir because the latter is removed on
    exit, taking the console with it.
    """
    candidates = (
        Path(QEMU_CONSOLE_LOG_NAME),
        Path(tempfile.gettempdir()) / QEMU_CONSOLE_LOG_NAME.lstrip("."),
    )
    for path in candidates:
        try:
            return open(path, "w"), path
        except OSError as e:
            logger.debug("QEMU guest console: cannot write %s (%s)", path, e)
    logger.warning("QEMU guest console: no writable log file; the console goes to the terminal only")
    return None, None


def _debug_log() -> None:
    sandbox_level = logging.DEBUG
    uvicorn_log_level = logging.ERROR
    format = "%(levelname)-5s [%(process)d] %(name)s: %(message)s"
    config_log(sandbox_level)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(uvicorn_log_level)
    logging.getLogger("uvicorn.error").setLevel(uvicorn_log_level)
    logging.getLogger("aiohttp_sse_client.client").setLevel(uvicorn_log_level)
    logging.getLogger("Pysandboxes").setLevel(logging.INFO)
    logging.getLogger("pysandboxes").setLevel(sandbox_level)
    logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(sandbox_level)
    logging.info("Start with python-sb")
    logging.basicConfig(
        level=sandbox_level,
        format=format,
    )


def main() -> int:
    """
    Parses command-line arguments and run the cpython in sandbox
    """
    with ExitStack() as stack:
        return _main(stack)


def _load_rules(config_path: Path, extra_rules: dict[str, set[str]]) -> AllRules:
    try:
        return load_and_parse_config(
            config_path=config_path,
            envs=os.environ,  # Use current environ
            **cast(Mapping[str, Any], extra_rules),
        )
    except ConfigSyntaxError as e:
        print(str(e), file=sys.stderr)
        sys.exit(-1)


def _main(stack: ExitStack) -> int:
    if DEBUG:
        _debug_log()

    python_parsed_args, sandboxes_args, python_cmd, config_path = parse_python_cmd_line(sys.argv[1:])

    extra_rules = convert_extra_rules(sandboxes_args)

    # If --learn and --pysandboxes-config=xxx, use --learn=xxx
    # If --learn and not --pysandboxes-config, use --learn=CONFIG_NAME
    # If -m module  use resource module/.py-sandboxes
    envs = extra_rules.get("env", set())
    # Not subject to the learn=false lock: it only forwards the terminal type, for the REPL's colors.
    envs.add("TERM=${TERM}")
    extra_rules["env"] = envs
    all_rules = _load_rules(config_path, extra_rules)
    lock = learn_lock(all_rules.config)
    if sandboxes_args and lock:
        print(
            f"{format_ruleref(lock)}: {lock.rule!r} locks the rules, the command line cannot add "
            f"{' '.join(sandboxes_args)}",
            file=sys.stderr,
        )
        sys.exit(-1)

    # The interactive IPython shell needs a writable profile directory. It gets a private, empty one
    # removed at exit, never the user's ~/.ipython: a write there (profile_default/startup/*.py) would run
    # unsandboxed in the user's next IPython session. Like a command-line rule, it is refused by a
    # learn=false lock: such a profile names its own IPython directory.
    if not python_cmd or "-i" in python_parsed_args:
        try:
            import IPython  # noqa: F401
        except ImportError:
            pass  # Ignore. IPython not found
        else:
            if lock:
                if not any(rule.rule.startswith("env=IPYTHONDIR=") for rule in all_rules.config):
                    # IPython then fails on its profile directory, and the shell falls back to the standard REPL.
                    print(
                        f"{format_ruleref(lock)}: {lock.rule!r} locks the rules, the IPython shell cannot get a "
                        "private profile directory, so the standard Python REPL runs instead. For IPython, add "
                        "`expose-rw=<dir>` and `env=IPYTHONDIR=<dir>` to the profile.",
                        file=sys.stderr,
                    )
            else:
                ipython_dir = stack.enter_context(tempfile.TemporaryDirectory(prefix="pysandboxes-ipython-"))
                extra_rules.setdefault("expose-rw", set()).add(ipython_dir)
                extra_rules["env"].add(f"IPYTHONDIR={ipython_dir}")
                all_rules = _load_rules(config_path, extra_rules)

    token = str(uuid.uuid4())
    log_level = logging.getLogger().getEffectiveLevel()

    _daemon: BaseDaemon = providers_factory[all_rules.os_sandbox](token, python_args=python_parsed_args)
    logger.debug(f"{_daemon=} {all_rules.learn=}")
    if "--version" in python_parsed_args:
        print("Python", ".".join(map(str, sys.version_info[0:3])))
        sys.exit(0)
    if isinstance(_daemon, NoneDaemon):
        from .lifecycle import enter
        from .remote.python_in_sb import python_in_sb

        # enter() without install(): the `none` provider is the documented
        # no-op of the README guard table. The flag says "this process is the
        # sandboxed one", which stays true even though no guard is patched in.
        enter()
        return python_in_sb(all_rules, python_cmd)
    os_provider = cast(BaseSubProcessDaemon, _daemon)
    _run_prefix = (
        cast(VMSSEDaemon, os_provider).host_run_temp_prefix
        if isinstance(os_provider, VMSSEDaemon)
        else "pysandboxes-sb-"
    )
    with tempfile.TemporaryDirectory(prefix=_run_prefix) as tmpdir:
        pipe_path = Path(tmpdir) / f"_{uuid.uuid4().hex}"
        pipe_path.unlink(missing_ok=True)
        launch_params: dict[str, Any] = {}
        if isinstance(os_provider, VMSSEDaemon):
            vm = cast(VMSSEDaemon, os_provider)
            # VM-based providers: build process_config before subprocess_cmd so the guest
            # image / boot media can embed config (provider-specific).
            vm.port = find_free_port() if all_rules.port == -1 else all_rules.port
            token = str(uuid.uuid4())
            # Propagate host terminal size to guest so console width/height match
            columns, lines = _get_terminal_size()
            guest_envs = Envs(
                {
                    **dict(all_rules.envs),
                    "COLUMNS": str(columns),
                    "LINES": str(lines),
                }
            )
            guest_all_rules = vm.augment_rules_for_guest_run_mount(all_rules._replace(envs=guest_envs))
            process_config = DaemonParameters(
                all_rules=guest_all_rules,
                log_level=log_level,
                log_format=get_log_formatter(),
                use_rich_handler=use_rich_handler(),
                token=token,
                port=vm.port,
                init_fn="",
                netfilter_rules=vm.guest_netfilter_rules(all_rules, vm.port),
                python_main_args=tuple(python_cmd),
                guest_run_dir=vm.guest_run_dir_mount(),
                guest_working_dir=str(Path.cwd().resolve()),
            )
            # Store config so subprocess_cmd can build boot media; guest reads config from mount
            vm._iso_config = process_config  # type: ignore[attr-defined]
            cmd, extra_envs = vm.subprocess_cmd(all_rules, envs=os.environ, pipe_path=pipe_path, temp=Path(tmpdir))

            # Config is in 9p-mounted config dir, no FIFO
            def _noop_config_writer(_: DaemonParameters) -> None:
                return None

            config_writer = _noop_config_writer
        else:
            os_provider.port = find_free_port() if all_rules.port == -1 else all_rules.port
            cmd, extra_envs = os_provider.subprocess_cmd(
                all_rules, envs=os.environ, pipe_path=pipe_path, temp=Path(tmpdir)
            )
            python_cmd.extend(["--_named-pipe", str(pipe_path), "--_python-sb"])
            token = str(uuid.uuid4())
            default_process_config = DaemonParameters(
                all_rules=all_rules,
                log_level=log_level,
                log_format=get_log_formatter(),
                use_rich_handler=use_rich_handler(),
                token=token,
                port=os_provider.port,
                init_fn="",
                python_main_args=(),
            )
            launch_params.update(
                getattr(
                    os_provider,
                    "get_launch_params_for_python_sb",
                    lambda *a, **k: {},
                )(all_rules, log_level, token, "", pipe_path, Path(tmpdir))
            )
            process_config = launch_params.get("process_config", default_process_config)
            config_writer = None

        env: Environ
        if all_rules.learn:
            env = {**os.environ, **all_rules.envs}
        else:
            env = dict(all_rules.envs)
        env = {**env, **extra_envs}

        if isinstance(os_provider, VMSSEDaemon):
            # QEMU is a host process, not the confined program, so the rules' environment
            # is not its environment: stripped of TMPDIR it falls back to /var/tmp for the
            # -snapshot scratch file, and a host where that is not writable fails with
            # "Could not open temporary file '/var/tmp/vl.XXXXXX': Read-only file system"
            # -- on a stream nobody reads, so the run exits 1 having printed nothing at
            # all. Point it at the run's own temp dir, writable by construction and
            # removed with it. Only the VM branch: the other providers exec a Python that
            # must not see a TMPDIR no rule granted.
            env = {**env, "TMPDIR": tmpdir}

        # Get optional launch extras (preexec_fn, pass_fds) for providers
        # that need custom child setup (e.g., unshare with slirp4netns fd)
        extra_preexec_fn, pass_fds = os_provider.get_launch_extras()

        launch_args = cmd if isinstance(os_provider, VMSSEDaemon) else cmd + python_cmd

        async def launch_and_wait() -> int:
            if isinstance(os_provider, VMSSEDaemon):
                vm = cast(VMSSEDaemon, os_provider)
                show_boot = vm.show_boot_console_truthy(all_rules)
                qemu_console_file: TextIO | None = None
                launch_kwargs: dict[str, Any] = dict(
                    cmd=launch_args,
                    pipe_path=pipe_path,
                    envs=Envs(env),
                    process_config=process_config,
                    extra_preexec_fn=extra_preexec_fn,
                    pass_fds=pass_fds,
                    on_launched=vm.on_process_launched,
                    config_writer=config_writer,
                )
                # Always use pipes so we can filter (sentinels) or tee to terminal + log file.
                launch_kwargs["stdout"] = subprocess.PIPE
                launch_kwargs["stderr"] = subprocess.PIPE
                if show_boot:
                    qemu_console_file, qemu_console_path = _open_qemu_console_log()
                    if qemu_console_path is not None:
                        # info, not debug: with a fallback the location is no longer
                        # predictable, and an unfindable log is not a log.
                        logger.info(
                            "QEMU guest console (terminal + tee) → %s",
                            qemu_console_path.resolve(),
                        )
                try:
                    # The guest writes its stderr to the shared run dir rather than to
                    # the console, which QEMU merges with stdout. Forward it as the guest
                    # produces it, so a long run reports on stderr while it is running,
                    # as it would without a VM.
                    with GuestStderrTail(Path(tmpdir) / GUEST_STDERR_FILE):
                        process = await launch_sandbox(**launch_kwargs)
                        try:
                            if process.stdout is None or process.stderr is None:
                                return shell_status(await process.wait())
                            # Full VM console only when qemu.show_boot_console=true (profile).
                            forward_all = show_boot
                            return await vm.wait_process_and_filter_console(
                                process,
                                forward_all=forward_all,
                                tee_file=qemu_console_file,
                            )
                        finally:
                            kill_slirp = getattr(vm, "_kill_slirp", None)
                            if callable(kill_slirp):
                                kill_slirp()
                finally:
                    if qemu_console_file is not None:
                        qemu_console_file.close()
            else:
                process = await launch_sandbox(
                    launch_args,
                    pipe_path,
                    envs=Envs(env),
                    process_config=process_config,
                    extra_preexec_fn=extra_preexec_fn,
                    pass_fds=launch_params.get("pass_fds", pass_fds),
                    on_launched=launch_params.get("on_launched", os_provider.on_process_launched),
                    config_writer=config_writer,
                )
                try:
                    return shell_status(await process.wait())
                finally:
                    kill_slirp = getattr(os_provider, "_kill_slirp", None)
                    if callable(kill_slirp):
                        kill_slirp()

        logger.debug("Launching sandbox (waiting for guest to finish)...")
        qemu_wait_rc = asyncio.run(launch_and_wait())
        return_code = qemu_wait_rc
        logger.debug("Guest process finished (QEMU wait exit code %s)", return_code)
        # VM guest writes exit code to shared run dir; prefer it over the hypervisor
        # process status (e.g. 9p latency; QEMU may return non-zero on shutdown I/O).
        if isinstance(os_provider, VMSSEDaemon):
            vm = cast(VMSSEDaemon, os_provider)
            exitcode_file = Path(tmpdir) / "exitcode"
            guest_rc = vm.read_guest_exitcode(exitcode_file)
            logger.debug(
                "QEMU exitcode: guest_rc=%s qemu_wait=%s file=%s",
                guest_rc,
                qemu_wait_rc,
                exitcode_file,
            )
            if guest_rc is not None:
                return_code = guest_rc
            elif qemu_wait_rc == 0:
                logger.debug(
                    "No guest exitcode at %s after wait; treating as failure",
                    exitcode_file,
                )
                return_code = 1
            else:
                return_code = qemu_wait_rc
        return return_code


if __name__ == "__main__":
    rc = 0
    try:
        rc = main()
    except SystemExit as e:
        rc = exit_status(e, report=True)
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:
        logger.error(f"Exception: {e}", exc_info=True)
        rc = -1
    if not sys.stdout.closed:
        sys.stdout.flush()
    if not sys.stderr.closed:
        sys.stderr.flush()
    os._exit(rc)
