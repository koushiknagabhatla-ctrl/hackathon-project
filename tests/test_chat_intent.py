"""What the assistant decides to do with a question, before any of it runs.

Two properties matter here and neither is visible from the reply text alone:

  * a question must never cause a WRITE. `create_civic_report` files into the
    ingest pipeline, and the trigger list used to contain the bare words
    "report", "issue" and "problem" - so "give me a detailed weather report"
    filed a civic complaint whose description was the user's own question.

  * an answer must cover what was asked and no more. "explain about this city"
    wants everything; "explain the traffic" wants traffic. Widening the second
    one answers six questions nobody asked.
"""

from __future__ import annotations

import pytest

from services.api.agents.chat import (
    _LEAKED_TOOL_MARKUP,
    BRIEFING_SEQUENCE,
    _looks_fabricated,
    _looks_like_scratchpad,
    _mentions_tool_names,
    _trim_reading,
    detect_intent,
)
from services.api.agents.chat_tools import handle_create_civic_report

WRITE_TOOL = "create_civic_report"


# ------------------------------------------------------- writes need intent
@pytest.mark.parametrize("question", [
    "give me a detailed weather report",
    "what is the traffic problem",
    "any issue in the city?",
    "show me the incident report",
    "explain about this city",
    "what happened in the last 24 hours",
])
def test_a_question_never_files_a_report(question):
    assert WRITE_TOOL not in detect_intent(question), (
        f"{question!r} would have written a civic report to the ledger"
    )


@pytest.mark.parametrize("statement", [
    "report a pothole on Eluru Road",
    "i want to report garbage dumping",
    "there is a broken streetlight near the bus stand",
    "file a complaint about waterlogging",
])
def test_an_actual_report_still_files(statement):
    assert WRITE_TOOL in detect_intent(statement)


def test_the_handler_refuses_a_question_even_if_it_is_called():
    """Defence in depth: the write itself checks what arrived."""
    out = handle_create_civic_report(
        {"issue_type": "other", "description": "what is the weather today?"},
        {"city_name": "Vijayawada", "latitude": 16.5, "longitude": 80.6},
    )
    assert out["report_created"] is False
    assert "nothing was filed" in out["message"].lower()


# ------------------------------------------------------- scope of an answer
@pytest.mark.parametrize("question,expected", [
    ("What is the current weather?", "get_weather"),
    ("find nearest hospitals", "search_nearby_services"),
    ("explain the traffic situation", "get_traffic_status"),
    ("tell me about the air quality in detail", "get_air_quality"),
])
def test_a_named_subject_keeps_the_answer_on_that_subject(question, expected):
    intents = detect_intent(question)
    assert expected in intents
    # naming a subject must not pull in the whole briefing
    assert not all(n in intents for n in BRIEFING_SEQUENCE), (
        f"{question!r} widened to a full briefing"
    )


@pytest.mark.parametrize("question", [
    "explain about this city",
    "city overview",
    "what do you know about Guntur",
    "give me everything",
])
def test_a_city_wide_question_gets_the_full_briefing(question):
    intents = detect_intent(question)
    missing = [n for n in BRIEFING_SEQUENCE if n not in intents]
    assert not missing, f"{question!r} skipped {missing}"


def test_a_thank_you_asks_for_nothing():
    assert detect_intent("thanks, that helps") == []


# ------------------------------------------- what a cloud model may not ship
# The cloud model writes the prose. These are the four ways it was actually
# caught putting something in an answer that no feed returned.

@pytest.mark.parametrize("answer", [
    "Wind is 3 km/h from the northwest (implied by the low speed).",
    "PM2.5 is probably around 45 ug/m3.",
    "Roughly 200 people were affected.",
    "The AQI is estimated at 130.",
])
def test_a_hedged_figure_is_rejected(answer):
    assert _looks_fabricated(answer), f"fabrication slipped through: {answer!r}"


@pytest.mark.parametrize("answer", [
    "Wind speed: 14.4 km/h (Open-Meteo, observed 11:45 UTC).",
    "Temperature 31.0 C, equivalent to 87.8 F.",
    "Measured flow 21 km/h against free-flow 30 km/h (70% of normal).",
    "No OpenAQ station within 25 km. No value is available.",
    "Two sources disagree: 34.3 C and 32.95 C.",
    "Population: 1,048,000 per the AP city registry.",
])
def test_a_grounded_figure_is_kept(answer):
    assert not _looks_fabricated(answer), f"false positive on: {answer!r}"


def test_reasoning_leaked_as_the_answer_is_rejected():
    leaked = ("We need to answer: \"explain about this city\". Use the provided "
              "readings only. We must list each item.")
    assert _looks_like_scratchpad(leaked)
    assert not _looks_like_scratchpad(
        "Vijayawada is reporting 3 critical incidents as of 15:24 UTC."
    )


def test_raw_tool_markup_is_rejected():
    assert _LEAKED_TOOL_MARKUP.search("<tool_call>\n<function=search_incidents>")
    assert not _LEAKED_TOOL_MARKUP.search(
        "Traffic is light: 21 km/h against a free-flow 30 km/h."
    )


def test_internal_tool_names_never_reach_the_reader():
    assert _mentions_tool_names("The get_city_status call returned 3 incidents.")
    assert not _mentions_tool_names(
        "The city status snapshot shows 3 active incidents."
    )


def test_trimming_caps_long_lists_and_says_so():
    trimmed = _trim_reading({"readings": [{"v": i} for i in range(52)]}, max_items=8)
    kept = trimmed["readings"]
    assert len(kept) == 9              # 8 readings plus the note
    assert "44 more not shown" in kept[-1]


def test_trimming_drops_internal_identifiers():
    trimmed = _trim_reading({"value": 12, "event_id": "evt_x", "evidence_id": "ev_y"})
    assert trimmed == {"value": 12}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
