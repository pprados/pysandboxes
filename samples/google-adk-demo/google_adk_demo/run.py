"""Run an ``LlmAgent`` via in-memory ``Runner`` and collect the final text response."""

import asyncio
import logging
from collections.abc import Generator, Iterable

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Event, Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types as genai_types

logger = logging.getLogger(__name__)


def _log_adk_event(event: Event) -> None:
    """One line per ADK event so ``-v`` shows progress while ``run_async`` is in progress."""
    if not logger.isEnabledFor(logging.INFO):
        return
    try:
        is_final = event.is_final_response()
    except Exception:
        is_final = False
    calls: list[str] = []
    if event.content and event.content.parts:
        for p in event.content.parts:
            if p.function_call:
                calls.append(p.function_call.name)
            if p.function_response:
                calls.append(f"→{p.function_response.name}")
    logger.info(
        "ADK event author=%r partial=%s final=%s tools=%s",
        getattr(event, "author", ""),
        getattr(event, "partial", False),
        is_final,
        calls or "—",
    )


def build_runner(agent: LlmAgent) -> Runner:
    """Construct a ``Runner`` wired with in-memory services and auto session creation."""
    return Runner(
        agent=agent,
        app_name="google_adk_demo",
        artifact_service=InMemoryArtifactService(),
        session_service=InMemorySessionService(),
        memory_service=InMemoryMemoryService(),
        auto_create_session=True,
    )


async def _run_turn_events(
    runner: Runner,
    user_text: str,
    *,
    max_llm_calls: int,
    user_id: str,
    session_id: str,
) -> list[Event]:
    """Run one user turn against an already-open ``Runner`` and collect its events."""
    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=user_text)],
    )
    run_config = RunConfig(
        max_llm_calls=max_llm_calls,
        streaming_mode=StreamingMode.NONE,
    )
    collected: list[Event] = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
        run_config=run_config,
    ):
        _log_adk_event(event)
        collected.append(event)
    return collected


def iter_runner_events(
    agent: LlmAgent,
    user_text: str,
    *,
    max_llm_calls: int,
    user_id: str = "cli_user",
    session_id: str = "cli_session",
) -> Generator[Event, None, None]:
    """Yield events from a fresh ``Runner`` for a single turn (via ``asyncio.run``)."""
    runner = build_runner(agent)

    async def _collect_events() -> list[Event]:
        # Sync ``Runner.run()`` delegates to a background thread; exceptions there do not
        # propagate, which yields empty output and exit 0. ``run_async`` in asyncio.run
        # surfaces model/API errors to the caller.
        async with runner:
            return await _run_turn_events(
                runner,
                user_text,
                max_llm_calls=max_llm_calls,
                user_id=user_id,
                session_id=session_id,
            )

    yield from asyncio.run(_collect_events())


async def run_agent_turn(
    runner: Runner,
    user_text: str,
    *,
    max_llm_calls: int,
    user_id: str = "chat_user",
    session_id: str = "chat_session",
) -> str:
    """Run one turn against an already-open ``Runner``, returning the assistant's text.

    ``auto_create_session=True`` means the first call creates the session; every later
    call with the same ``user_id``/``session_id`` reuses it (``Runner.run_async`` calls
    ``session_service.get_session`` before creating one), so ADK's own session carries
    the conversation across turns instead of a hand-rolled message list.
    """
    events = await _run_turn_events(
        runner,
        user_text,
        max_llm_calls=max_llm_calls,
        user_id=user_id,
        session_id=session_id,
    )
    return extract_final_text_from_events(events)


def extract_final_text_from_events(events: Iterable[Event]) -> str:
    """Keep the last ``Content`` from an event marked as final (no streaming partials)."""
    final_text = ""
    last_model_text = ""
    for event in events:
        if getattr(event, "partial", False):
            continue
        if event.content and event.content.parts:
            chunk = "".join(
                part.text for part in event.content.parts if part.text and not getattr(part, "thought", False)
            )
            if chunk.strip():
                last_model_text = chunk
                if event.is_final_response():
                    final_text = chunk
    out = final_text.strip() or last_model_text.strip()
    return out


def run_agent_once(
    agent: LlmAgent,
    user_text: str,
    *,
    max_llm_calls: int,
) -> str:
    """Run one user turn and return assistant text."""
    return extract_final_text_from_events(iter_runner_events(agent, user_text, max_llm_calls=max_llm_calls))
