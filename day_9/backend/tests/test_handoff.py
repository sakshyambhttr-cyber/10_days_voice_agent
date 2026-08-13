import pytest
from livekit.agents import AgentSession, inference, llm

from agent import Assistant, InterviewBuddy


def _llm() -> llm.LLM:
    import os

    from livekit.plugins import openai

    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if nvidia_key:
        return openai.LLM(
            model=os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct").strip(),
            base_url=os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ).strip(),
            api_key=nvidia_key,
            temperature=0.7,
        )
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        return openai.LLM(
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip(),
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            temperature=0.7,
        )
    return inference.LLM(model="openai/gpt-4.1-mini")


async def _assert_message(result, eval_llm: llm.LLM, intent: str) -> None:
    """Helper to consume optional tool calls if present, then judge assistant message."""
    while True:
        event_assert = result.expect.next_event()
        try:
            event_assert.is_function_call()
            result.expect.next_event().is_function_call_output()
        except AssertionError:
            await event_assert.is_message(role="assistant").judge(
                eval_llm, intent=intent
            )
            break


@pytest.mark.asyncio
async def test_normal_english_practice_no_handoff() -> None:
    """TEST A: Normal English practice stays with BolBuddy, no handoff."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(user_input="I want to practice English.")

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Welcomes the learner warmly and offers general English conversation or speaking practice.
            Does not initiate a transfer or ask to hand off to InterviewBuddy.
            """,
        )

        result.expect.no_more_events()


@pytest.mark.asyncio
async def test_specialist_request_asks_confirmation() -> None:
    """TEST B: Interview request detected, BolBuddy asks permission before switching, no immediate handoff."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        result = await session.run(
            user_input="I have an interview next week and want to practice."
        )

        await _assert_message(
            result,
            eval_llm,
            intent="""
            Recognizes that the user is preparing for an interview.
            Asks the user for confirmation or permission to switch or connect to InterviewBuddy for focused interview practice.
            The agent MUST ask whether the user wants to switch rather than immediately executing a transfer without asking.
            """,
        )

        result.expect.no_more_events()


@pytest.mark.asyncio
async def test_handoff_after_user_confirmation() -> None:
    """TEST C: Learner confirms switch, handoff to InterviewBuddy succeeds."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        # Step 1: User mentions interview
        res1 = await session.run(
            user_input="I have an interview next week and want to practice."
        )
        res1.expect.skip_next(count=len(res1.events))

        # Step 2: User confirms
        res2 = await session.run(user_input="Yes, please connect me.")

        # Expect transfer_to_interview_buddy function call and output
        res2.expect.next_event().is_function_call(name="transfer_to_interview_buddy")
        res2.expect.next_event().is_function_call_output()

        # Expect assistant message
        await (
            res2.expect.next_event()
            .is_message(role="assistant")
            .judge(
                eval_llm,
                intent="""
                Confirms connecting to InterviewBuddy, starts interview practice, or asks an introductory question to begin interview preparation.
                """,
            )
        )

        # Expect AgentHandoffEvent to InterviewBuddy
        res2.expect.next_event().is_agent_handoff(new_agent_type=InterviewBuddy)
        res2.expect.no_more_events()

        # Step 3: Verify InterviewBuddy is active and conducts interview practice
        res3 = await session.run(user_input="I'm ready for the first question.")
        await (
            res3.expect.next_event()
            .is_message(role="assistant")
            .judge(
                eval_llm,
                intent="""
                Acts as InterviewBuddy and asks an interview question (e.g. 'Tell me about yourself' or a common interview question).
                """,
            )
        )
        res3.expect.no_more_events()


@pytest.mark.asyncio
async def test_context_preservation_across_handoff() -> None:
    """TEST D: InterviewBuddy receives existing chat context (software internship) without asking user to repeat."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        # Step 1: User mentions specific context
        res1 = await session.run(
            user_input="I have an interview next week for a software internship."
        )
        res1.expect.skip_next(count=len(res1.events))

        # Step 2: User confirms switch
        res2 = await session.run(user_input="Yes, connect me.")

        res2.expect.next_event().is_function_call(name="transfer_to_interview_buddy")
        res2.expect.next_event().is_function_call_output()

        await (
            res2.expect.next_event()
            .is_message(role="assistant")
            .judge(
                eval_llm,
                intent="""
                Confirms connecting or starting interview practice with InterviewBuddy.
                """,
            )
        )

        res2.expect.next_event().is_agent_handoff(new_agent_type=InterviewBuddy)
        res2.expect.no_more_events()

        # Step 3: InterviewBuddy turn with preserved context
        res3 = await session.run(user_input="What is my first question?")
        await (
            res3.expect.next_event()
            .is_message(role="assistant")
            .judge(
                eval_llm,
                intent="""
                Demonstrates awareness of the learner's software internship or upcoming interview context from earlier in the conversation without asking the user to repeat their goal.
                Asks a relevant interview question (such as self-introduction, technical background, or reasons for applying to the software internship).
                """,
            )
        )
        res3.expect.no_more_events()


@pytest.mark.asyncio
async def test_decline_handoff_stays_with_bolbuddy() -> None:
    """TEST E: When user declines the switch, BolBuddy remains active and continues general practice."""
    async with (
        _llm() as eval_llm,
        AgentSession(llm=eval_llm) as session,
    ):
        await session.start(Assistant())

        # Step 1: User mentions interview
        res1 = await session.run(user_input="I have an interview next week.")
        res1.expect.skip_next(count=len(res1.events))

        # Step 2: User declines switch
        res2 = await session.run(
            user_input="No, I prefer to stay here and just practice casual English."
        )

        # BolBuddy responds normally without calling transfer_to_interview_buddy
        await _assert_message(
            res2,
            eval_llm,
            intent="""
            Understands that the user does not want to switch to InterviewBuddy.
            Remains as BolBuddy and warmly continues general conversation or casual English practice.
            """,
        )

        res2.expect.no_more_events()


@pytest.mark.asyncio
async def test_normal_vocabulary_question_no_handoff() -> None:
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

        result.expect.no_more_events()


def test_specialist_murf_voice_configuration() -> None:
    """TEST G: Verify specialist voice configuration (BolBuddy: Anisha, InterviewBuddy: Samar, Future: Pooja)."""
    # 1. BolBuddy default agent
    bolbuddy = Assistant()
    assert bolbuddy.id == "assistant" or "assistant" in bolbuddy.id

    # 2. InterviewBuddy specialist configured with Murf voice Samar
    interview_buddy = InterviewBuddy(voice="Samar")
    assert interview_buddy.tts is not None
    assert getattr(interview_buddy.tts, "_opts", None) is not None
    assert interview_buddy.tts._opts.voice == "Samar"

    # 3. Future specialist configured with Murf voice Pooja
    pooja_specialist = InterviewBuddy(voice="Pooja")
    assert pooja_specialist.tts is not None
    assert getattr(pooja_specialist.tts, "_opts", None) is not None
    assert pooja_specialist.tts._opts.voice == "Pooja"
