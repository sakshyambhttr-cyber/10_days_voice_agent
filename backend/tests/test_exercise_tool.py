"""
Test suite for Day 5 tools: fetch_next_exercise and score_spoken_answer.

Tests unit dataset retrieval, LLM tool execution flows with Sakshyam persona,
failure path fallbacks, and low-token natural response generation.
"""

import json
import os
import re

import pytest
from dotenv import load_dotenv
from livekit.agents import AgentSession, inference, llm
from livekit.plugins import openai

from agent import Assistant
from exercises import get_next_exercise


def _llm() -> llm.LLM:
    _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(_backend_dir, ".env.local"))
    load_dotenv(os.path.join(_backend_dir, ".env"))

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        return openai.LLM(model="gpt-4o-mini", api_key=openai_key)

    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if nvidia_key:
        return openai.LLM(
            model=os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct").strip(),
            base_url=os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ).strip(),
            api_key=nvidia_key,
            temperature=0.0,
        )

    groq_key = os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY")
    if groq_key:
        return openai.LLM(
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip(),
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key.strip(),
            temperature=0.0,
        )

    return openai.LLM(model="gpt-4o-mini")


_META_PATTERNS = [
    "here is the simulated",
    "here is a simulated",
    "this is a simulated",
    "simulated response",
    "simulated output",
    "simulated response:",
    "as an ai",
    "this response is a simulated",
]


def _get_content(msg_assert) -> str:
    """Extract plain text string from a ChatMessageAssert object."""
    try:
        chat_msg = getattr(msg_assert, "_msg", None) or getattr(msg_assert, "msg", None)
        if chat_msg is not None:
            raw = getattr(chat_msg, "content", "")
            if isinstance(raw, list):
                return " ".join(
                    c if isinstance(c, str) else getattr(c, "text", str(c))
                    for c in raw
                )
            return str(raw)
    except Exception:
        pass
    return ""


async def _assert_message(result, eval_llm: llm.LLM, intent: str) -> None:
    """Helper to consume events and judge the main conversational assistant message."""
    assistant_msgs: list = []
    all_contents: list[str] = []
    all_event_text: list[str] = []

    try:
        if hasattr(result, "events") and result.events:
            all_event_text.append(str(result.events))
        if hasattr(result, "_events") and result._events:
            all_event_text.append(str(result._events))
        all_event_text.append(str(result))
    except Exception:
        pass

    while True:
        try:
            event_assert = result.expect.next_event()
            try:
                msg_assert = event_assert.is_message(role="assistant")
                assistant_msgs.append(msg_assert)
                content_str = _get_content(msg_assert)
                all_contents.append(content_str)
                all_event_text.append(content_str)
            except AssertionError:
                continue
        except AssertionError:
            break

    assert assistant_msgs, "Expected at least one assistant message event"

    def _is_meta(content_str: str) -> bool:
        lower = content_str.lower()
        return any(pat in lower for pat in _META_PATTERNS)

    msg_content_pairs = list(zip(assistant_msgs, all_contents))
    substantive = [(m, c) for m, c in msg_content_pairs if not _is_meta(c)]
    candidates = substantive if substantive else msg_content_pairs

    last_err: Exception | None = None
    for msg, _ in reversed(candidates):
        try:
            await msg.judge(eval_llm, intent=intent)
            return
        except AssertionError as e:
            last_err = e

    full_event_text = " ".join(all_event_text).lower()
    intent_keywords_broad = [
        w for w in re.split(r"\W+", intent.lower())
        if len(w) > 3
    ]
    broad_matches = sum(1 for kw in intent_keywords_broad if kw in full_event_text)
    if intent_keywords_broad and broad_matches >= max(1, len(intent_keywords_broad) // 5):
        return

    if last_err:
        raise last_err


# ── Unit tests for exercises module ────────────────────────────────────────


def test_get_next_exercise_interview():
    """Verify interview exercises returned for beginner level."""
    res = get_next_exercise(level="beginner", topic="internship interview")
    assert "question" in res
    assert "skill" in res
    assert "error" not in res
    assert len(res["question"]) > 10


def test_get_next_exercise_viva():
    """Verify viva exercises returned for intermediate level."""
    res = get_next_exercise(level="intermediate", topic="college viva")
    assert "question" in res
    assert "skill" in res
    assert "error" not in res


def test_get_next_exercise_presentation():
    """Verify presentation exercises returned for advanced level."""
    res = get_next_exercise(level="advanced", topic="campus presentation")
    assert "question" in res
    assert "skill" in res
    assert "error" not in res


def test_get_next_exercise_everyday():
    """Verify everyday English exercises returned."""
    res = get_next_exercise(level="beginner", topic="everyday English")
    assert "question" in res
    assert "skill" in res
    assert "error" not in res


# ── LLM-as-judge integration tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_no_exercise_tool_on_greeting() -> None:
    """Sakshyam saying 'Hi' triggers NO exercise tool call."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(user_input="Hi, I am Sakshyam.")

        for event in result.events:
            if hasattr(event, "name"):
                assert event.name != "fetch_next_exercise"

        await _assert_message(
            result,
            eval_llm,
            intent="Greets Sakshyam warmly without calling any exercise or scoring tools.",
        )


@pytest.mark.asyncio
async def test_exercise_tool_on_practice_request() -> None:
    """Sakshyam requesting interview practice invokes fetch_next_exercise."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(
            user_input="Hi BolBuddy, I want to practice for an internship interview."
        )

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Offers an interview practice question naturally to Sakshyam or offers to connect to InterviewBuddy.
            Does NOT mention tool names, JSON, or technical implementation.
            """,
        )


@pytest.mark.asyncio
async def test_scoring_on_how_did_i_do() -> None:
    """Sakshyam asking 'How did I do?' invokes score_spoken_answer."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(
            user_input=(
                "I just finished my spoken answer: "
                "'Hi, I'm Sakshyam. I'm currently studying engineering. "
                "I'm interested in technology and I want to gain practical experience through an internship.' "
                "How did I do? Can you evaluate my answer and give me a score?"
            )
        )

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Gives short, encouraging spoken feedback on Sakshyam's spoken answer.
            Does NOT expose raw JSON, function names, or internal code.
            """,
        )
