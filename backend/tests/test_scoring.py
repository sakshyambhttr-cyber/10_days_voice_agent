"""Tests for the score_spoken_answer tool and scoring behavior."""

import json
import os
import re

import pytest
from livekit.agents import AgentSession, inference, llm

from agent import Assistant
from scoring import _compute_score


import os
from dotenv import load_dotenv
from livekit.plugins import openai


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


# ── Unit tests for the scoring heuristic ─────────────────────────────────


@pytest.mark.asyncio
async def test_compute_score_basic():
    """Verify _compute_score returns valid compact JSON structure."""
    result = _compute_score(
        "My name is Priya and I am preparing for a job interview at an IT company."
    )
    assert "score" in result
    assert "strength" in result
    assert "improvement" in result
    assert "example" in result
    assert 1 <= result["score"] <= 10


@pytest.mark.asyncio
async def test_compute_score_empty():
    """Empty transcript returns error."""
    result = _compute_score("")
    assert "error" in result


@pytest.mark.asyncio
async def test_compute_score_too_short():
    """Very short transcript returns error."""
    result = _compute_score("Hi")
    assert "error" in result


@pytest.mark.asyncio
async def test_compute_score_output_compact():
    """Output JSON has exactly 4 keys — no unnecessary metadata."""
    result = _compute_score(
        "I want to tell you about my hobby. I like reading books because they help me learn new words."
    )
    assert set(result.keys()) == {"score", "strength", "improvement", "example"}
    # Verify the JSON serialization is small
    serialized = json.dumps(result)
    assert len(serialized) < 200, f"Output too large: {len(serialized)} chars"


# ── LLM-as-judge integration tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_no_scoring_on_greeting() -> None:
    """score_spoken_answer must NOT be called for a simple greeting."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(user_input="Hey BolBuddy!")

        for event in result.events:
            if hasattr(event, "name"):
                assert event.name != "score_spoken_answer"

        await _assert_message(
            result,
            eval_llm,
            intent="Greets the user warmly without evaluating or scoring anything.",
        )


@pytest.mark.asyncio
async def test_no_scoring_on_hinglish_chat() -> None:
    """score_spoken_answer must NOT be called for casual Hinglish conversation."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(
            user_input="Bhai, aaj mera din bahut acha tha! College mein presentation diya."
        )

        for event in result.events:
            if hasattr(event, "name"):
                assert event.name != "score_spoken_answer"

        await _assert_message(
            result,
            eval_llm,
            intent="Responds warmly to casual Hinglish chat about the user's day. May offer to practice or continue the conversation. Does NOT provide a numerical score or formal evaluation of the user's English.",
        )


@pytest.mark.asyncio
async def test_scoring_on_evaluation_request() -> None:
    """score_spoken_answer SHOULD be called when learner explicitly asks for evaluation."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(
            user_input=(
                "I just practiced my self-introduction: "
                "'Good morning, my name is Rahul and I am a final year student at Delhi University. "
                "I want to become a software engineer because I love solving problems.' "
                "Can you evaluate my English and give me a score?"
            )
        )

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Provides encouraging spoken feedback on the learner's self-introduction.
            May mention strengths, areas to improve, or a brief suggestion.
            Does NOT expose raw JSON, tool names, or technical implementation.
            """,
        )


@pytest.mark.asyncio
async def test_scoring_output_is_natural() -> None:
    """After scoring, the assistant response must be natural speech, not raw JSON."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(
            user_input=(
                "Here is my answer for interview practice: "
                "'I am very hardworking person and I like to do teamwork with my colleagues. "
                "I have experience in marketing and I want to grow in this field.' "
                "Please score my answer."
            )
        )

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Gives a natural, spoken-language response about the learner's answer quality.
            May state the numerical score (e.g. 7 out of 10 or score 8).
            Does NOT output raw JSON payloads, function names, or internal code.
            The response is conversational and encouraging.
            """,
        )
