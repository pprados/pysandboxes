"""Event extraction helper tests (no Runner)."""

from collections.abc import Generator

from google.adk.runners import Event
from google.genai import types as genai_types

from google_adk_demo.run import extract_final_text_from_events


def test_extract_final_text_prefers_last_final() -> None:
    def gen() -> Generator[Event, None, None]:
        yield Event(
            author="demo_agent",
            partial=False,
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part(text="draft")],
            ),
        )
        yield Event(
            author="demo_agent",
            partial=False,
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part(text="final answer")],
            ),
        )

    assert extract_final_text_from_events(gen()) == "final answer"
