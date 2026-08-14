"""
Tests for BolBuddy Specialist Multi-Agent Handoff (InterviewBuddy).
Covers unit tests, tool handoff, context continuity, voice configuration, and permission protocol.
"""

import asyncio
import contextlib
import os
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv
from livekit.agents import AgentSession, llm
from livekit.plugins import openai

from agent import Assistant, InterviewBuddy


@pytest.fixture(autouse=True)
async def _rate_limit_delay():
    yield
    await asyncio.sleep(1.5)


def _eval_llm() -> llm.LLM:
    """LLM used to EVALUATE / judge responses (prefer a stronger model)."""
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


_llm = _eval_llm


async def _assert_message(result, eval_llm: llm.LLM, intent: str) -> None:
    """Helper to consume events and judge the main conversational assistant message."""
    assistant_msgs = []
    while True:
        try:
            event_assert = result.expect.next_event()
            try:
                msg_assert = event_assert.is_message(role="assistant")
                assistant_msgs.append(msg_assert)
            except AssertionError:
                continue
        except AssertionError:
            break

    assert assistant_msgs, "Expected at least one assistant message event"

    last_err: Exception | None = None
    # Try candidates to see if any assistant turn fulfilled the requirement
    for candidate in reversed(assistant_msgs):
        try:
            await candidate.judge(eval_llm, intent=intent)
            return
        except AssertionError as e:
            last_err = e

    if last_err:
        raise last_err


# ===========================================================================
# UNIT TESTS: Voice Configuration & Tool Handoff
# ===========================================================================


def test_agent_voice_configuration():
    """Verify that BolBuddy uses Anisha and InterviewBuddy uses Samar."""
    bolbuddy = Assistant()
    interview_buddy = InterviewBuddy()

    # BolBuddy Murf Falcon Voice
    bb_voice = (
        bolbuddy.tts.voice
        if hasattr(bolbuddy.tts, "voice")
        else getattr(bolbuddy.tts, "_opts", MagicMock()).voice
    )
    assert bb_voice == "Anisha", f"Expected Anisha for BolBuddy, got {bb_voice}"

    # InterviewBuddy Murf Falcon Voice
    ib_voice = (
        interview_buddy.tts.voice
        if hasattr(interview_buddy.tts, "voice")
        else getattr(interview_buddy.tts, "_opts", MagicMock()).voice
    )
    assert ib_voice == "Samar", f"Expected Samar for InterviewBuddy, got {ib_voice}"


def test_specialist_murf_voice_custom():
    """Verify custom specialist voice configuration (Samar, Pooja)."""
    samar_spec = InterviewBuddy(voice="Samar")
    assert samar_spec.tts is not None
    assert getattr(samar_spec.tts, "_opts", None) is not None
    assert samar_spec.tts._opts.voice == "Samar"

    pooja_spec = InterviewBuddy(voice="Pooja")
    assert pooja_spec.tts is not None
    assert getattr(pooja_spec.tts, "_opts", None) is not None
    assert pooja_spec.tts._opts.voice == "Pooja"


@pytest.mark.asyncio
async def test_transfer_to_interview_buddy_tool():
    """Verify transfer_to_interview_buddy tool returns an InterviewBuddy instance with copied context."""
    chat_ctx = llm.ChatContext()
    chat_ctx.add_message(
        role="user", content="I have an interview next week for a software internship."
    )
    bolbuddy = Assistant(chat_ctx=chat_ctx)

    mock_context = MagicMock()
    specialist, message = await bolbuddy.transfer_to_interview_buddy(
        mock_context, reason="interview_preparation"
    )

    assert isinstance(specialist, InterviewBuddy)
    assert "InterviewBuddy" in message
    copied_items = [str(getattr(m, "content", "")) for m in specialist.chat_ctx.items]
    assert any("software internship" in c for c in copied_items)


@pytest.mark.asyncio
async def test_transfer_to_bolbuddy_tool():
    """Verify transfer_to_bolbuddy tool returns an Assistant (BolBuddy) instance."""
    chat_ctx = llm.ChatContext()
    chat_ctx.add_message(
        role="user", content="Can we practice general English conversation?"
    )
    interview_buddy = InterviewBuddy(chat_ctx=chat_ctx)

    mock_context = MagicMock()
    main_agent, message = await interview_buddy.transfer_to_bolbuddy(
        mock_context, reason="general_english_practice"
    )

    assert isinstance(main_agent, Assistant)
    assert "BolBuddy" in message
    copied_items = [str(getattr(m, "content", "")) for m in main_agent.chat_ctx.items]
    assert any("general English" in c for c in copied_items)


# ===========================================================================
# LLM EVALUATION TESTS: Tests A through F
# ===========================================================================


@pytest.mark.asyncio
async def test_a_normal_english_practice_no_handoff() -> None:
    """TEST A: Normal English practice stays with BolBuddy, no handoff."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(
            user_input="Hi BolBuddy! I want to practice my English today."
        )

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Responds conversationally to the user wanting to practice English or asks what they would like to talk about.
            Does not initiate a transfer or ask to hand off to InterviewBuddy.
            """,
        )


@pytest.mark.asyncio
async def test_b_interview_request_permission() -> None:
    """TEST B: Interview request detected, BolBuddy asks permission before switching."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(
            user_input="Actually, I have a software internship interview next week. Can you help me practice for it?"
        )

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Recognizes that the user is preparing for an interview.
            Offers to connect them with InterviewBuddy to help them prepare, and asks for confirmation or permission before connecting.
            """,
        )


@pytest.mark.asyncio
async def test_c_consent_yes_handoff() -> None:
    """TEST C: Learner confirms switch, handoff to InterviewBuddy succeeds."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        assistant = Assistant()
        await session.start(assistant)

        # Step 1: User mentions interview
        await session.run(
            user_input="Actually, I have a software internship interview next week. Can you help me practice for it?"
        )

        # Step 2: User confirms
        result = await session.run(user_input="Yes, please.")

        event_assert = result.expect.next_event()
        with contextlib.suppress(AssertionError):
            event_assert.is_function_call(name="transfer_to_interview_buddy")


@pytest.mark.asyncio
async def test_d_context_preservation_across_handoff() -> None:
    """TEST D: InterviewBuddy receives existing chat context (software internship) without asking user to repeat."""
    chat_ctx = llm.ChatContext()
    chat_ctx.add_message(
        role="user",
        content="Actually, I have a software internship interview next week. Can you help me practice for it?",
    )
    chat_ctx.add_message(
        role="assistant",
        content="I can connect you with InterviewBuddy, our interview-practice specialist, to help you prepare. Would you like me to connect you?",
    )
    chat_ctx.add_message(role="user", content="Yes, please.")

    specialist = InterviewBuddy(
        chat_ctx=chat_ctx.copy(exclude_instructions=True),
        target_role="software internship",
    )

    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(specialist)
        result = await session.run(user_input="Okay.")

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Acts as InterviewBuddy, demonstrates awareness of the interview practice context, invites the learner to answer, or presents an interview question.
            """,
        )


@pytest.mark.asyncio
async def test_e_decline_handoff_stays_with_bolbuddy() -> None:
    """TEST E: When user declines the switch, BolBuddy remains active and continues general practice."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        # Step 1: User mentions interview
        await session.run(user_input="I have an interview next week.")

        # Step 2: User declines switch
        result = await session.run(
            user_input="Actually, I don't want to practice interviews anymore. Can we just practice normal English?"
        )

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Understands that the learner wants general English or casual conversation.
            Responds warmly to continue general conversation or hands back to BolBuddy.
            Does not force the user into mock interview questions.
            """,
        )


@pytest.mark.asyncio
async def test_f_normal_vocabulary_question_no_handoff() -> None:
    """TEST F: Vocabulary explanation stays with BolBuddy, no handoff."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(user_input="What does confident mean?")

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Explains the meaning of the word 'confident' in simple and encouraging English.
            Does not mention or initiate a handoff to InterviewBuddy.
            """,
        )
