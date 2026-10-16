# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Coverage-guided fuzz targets for untrusted parsers and transport data."""

import ast
import json
import os
import sys
import warnings

import atheris

TARGET = os.environ["FUZZ_TARGET"]
warnings.filterwarnings("ignore", category=SyntaxWarning)

with atheris.instrument_imports(
    include=(
        "pysandboxes.eval_rules",
        "pysandboxes.eval_transform",
        "pysandboxes.remote.tools",
        "pysandboxes.remote.base_sse_daemon",
    )
):
    from pathlib import Path

    from pysandboxes.e import EvalSyntaxRejected, RestrictedUnpicklingError, SandBoxProtocolError
    from pysandboxes.eval_rules import DEFAULT_RULES, parse_rules
    from pysandboxes.eval_transform import inject, validate
    from pysandboxes.guard_eval import _raise_parse_overflow
    from pysandboxes.remote.base_sse_daemon import _rebuild_remote_exception
    from pysandboxes.remote.tools import check_sse_line, from_b85_restricted, result_predicate
    from pysandboxes.sb_types import ConfigLine


def _fuzz_eval_rules(data: bytes) -> None:
    text = data.decode("utf-8", errors="replace")
    config = [ConfigLine(f"eval-{line}", Path("<atheris>"), number) for number, line in enumerate(text.splitlines(), 1)]
    parse_rules(config, [])


def _fuzz_eval_transform(data: bytes) -> None:
    source = data.decode("utf-8", errors="replace")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return
    except (RecursionError, MemoryError):
        try:
            _raise_parse_overflow("<atheris>", source)
        except EvalSyntaxRejected:
            return
    validate(tree, DEFAULT_RULES)
    inject(tree)


def _try_restricted_pickle(payload: str) -> None:
    try:
        from_b85_restricted(payload, result_predicate)
    except RestrictedUnpicklingError:
        return


def _fuzz_restricted_pickle(data: bytes) -> None:
    _try_restricted_pickle(data.decode("latin-1"))


def _fuzz_sse(data: bytes) -> None:
    try:
        event_data = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    try:
        check_sse_line(event_data)
    except SandBoxProtocolError:
        return
    try:
        message = json.loads(event_data)
    except json.JSONDecodeError:
        return
    if not isinstance(message, dict):
        return
    result = message.get("result")
    if isinstance(result, str):
        _try_restricted_pickle(result)
    exception = message.get("exception")
    fallback = message.get("exception_fallback")
    if isinstance(exception, str) and (fallback is None or isinstance(fallback, str)):
        try:
            _rebuild_remote_exception(exception, fallback)
        except RestrictedUnpicklingError:
            return


_TARGETS = {
    "eval_rules": _fuzz_eval_rules,
    "eval_transform": _fuzz_eval_transform,
    "restricted_pickle": _fuzz_restricted_pickle,
    "sse": _fuzz_sse,
}


def main() -> None:
    """Run the requested target under libFuzzer."""
    target = _TARGETS[TARGET]
    atheris.Setup(sys.argv, target)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
