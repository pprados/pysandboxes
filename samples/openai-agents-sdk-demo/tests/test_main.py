"""Tests for CLI and async runner (mocked)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openai_agents_sdk_demo import main as main_mod


@pytest.mark.asyncio
async def test_run_agent_async_returns_final_output(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = MagicMock()
    fake.final_output = "  All done.  "
    monkeypatch.setattr(main_mod.Runner, "run", AsyncMock(return_value=fake))

    text = await main_mod.run_agent_async("task", max_turns=5, model="gpt-4o-mini")
    assert text == "All done."
    main_mod.Runner.run.assert_awaited_once()
    call_kw = main_mod.Runner.run.call_args.kwargs
    assert call_kw["max_turns"] == 5


def test_main_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def fake_run(*args: object, **kwargs: object) -> str:
        return "ok"

    monkeypatch.setattr(main_mod, "run_agent_async", fake_run)
    rc = main_mod.main(["--task", "do something"])
    assert rc == 0


def test_main_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def boom(*args: object, **kwargs: object) -> str:
        raise RuntimeError("x")

    monkeypatch.setattr(main_mod, "run_agent_async", boom)
    rc = main_mod.main(["--task", "do something"])
    assert rc == 1
