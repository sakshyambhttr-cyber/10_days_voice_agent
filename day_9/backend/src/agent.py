import asyncio
import logging
import os

import httpx
from dotenv import load_dotenv

# pyrefly: ignore [missing-import]
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    llm,
    tokenize,
    tts,
)
from livekit.agents.job import JobExecutorType
from livekit.agents.types import NOT_GIVEN

# pyrefly: ignore [missing-import]
from livekit.plugins import deepgram, google, murf, openai, silero

from db import (
    finalize_call,
    get_or_create_user,
    init_db,
    mark_call_outcome,
    record_call_start,
)
from escalation_tools import (
    create_escalation as fn_create_escalation,
)
from exercises import (
    get_next_exercise as fn_get_next_exercise,
)
from memory_tools import (
    async_prefetch_user_memory,
)
from memory_tools import (
    forget_my_data as fn_forget_my_data,
)
from memory_tools import (
    lookup_user_memory as fn_lookup_user_memory,
)
from memory_tools import (
    save_user_memory as fn_save_user_memory,
)
from memory_tools import (
    what_do_you_remember as fn_what_do_you_remember,
)
from prompts.interview_prompt import INTERVIEW_BUDDY_PROMPT
from prompts.system_prompt import SYSTEM_PROMPT
from rag import (
    search_learning_resources as fn_search_learning_resources,
)
from scoring import (
    score_spoken_answer as fn_score_spoken_answer,
)

logger = logging.getLogger("agent")
load_dotenv(".env.local")


def _prune_history(session: AgentSession, max_turns: int = 6) -> None:
    """Keep system prompt + most recent max_turns messages and filter out raw function JSON leakage."""
    try:
        if (
            hasattr(session, "chat_ctx")
            and session.chat_ctx
            and hasattr(session.chat_ctx, "messages")
        ):
            msgs = session.chat_ctx.messages
            # Filter out any raw tool JSON leakage messages
            cleaned_msgs = []
            for m in msgs:
                content = str(getattr(m, "content", "") or "")
                if (
                    '{"name":' in content
                    or '{"who_needs_help"' in content
                    or '"parameters":' in content
                    or "</function>" in content
                    or "create_escalation" in content
                    or "fetch_next_exercise" in content
                    or "score_spoken_answer" in content
                    or ">{" in content
                ):
                    continue
                cleaned_msgs.append(m)

            if len(cleaned_msgs) > max_turns + 1:
                system_msg = (
                    [cleaned_msgs[0]]
                    if (
                        cleaned_msgs
                        and getattr(cleaned_msgs[0], "role", None) == "system"
                    )
                    else []
                )
                recent_msgs = cleaned_msgs[-max_turns:]
                session.chat_ctx.messages = system_msg + [
                    m for m in recent_msgs if m not in system_msg
                ]
            else:
                session.chat_ctx.messages = cleaned_msgs
    except Exception as e:
        logger.warning(f"Chat context pruning exception: {e}")


def _clean_and_copy_chat_ctx(
    chat_ctx: llm.ChatContext | None, max_turns: int = 4
) -> llm.ChatContext | None:
    """Create a clean, lightweight copy of chat context stripped of heavy tool outputs and old bloat."""
    if not chat_ctx:
        return None
    copied = chat_ctx.copy(exclude_instructions=True)
    if hasattr(copied, "messages") and copied.messages:
        cleaned_msgs = []
        for m in copied.messages:
            role = getattr(m, "role", None)
            if role in ("tool", "system", "developer"):
                continue
            content = str(getattr(m, "content", "") or "")
            if (
                '{"name":' in content
                or '"parameters":' in content
                or "</function>" in content
                or "create_escalation" in content
                or "fetch_next_exercise" in content
                or "score_spoken_answer" in content
                or ">{" in content
            ):
                continue
            cleaned_msgs.append(m)
        copied.messages = (
            cleaned_msgs[-max_turns:]
            if len(cleaned_msgs) > max_turns
            else cleaned_msgs
        )
    return copied


_TTS_CACHE: dict[str, murf.TTS] = {}


def create_murf_tts(
    voice: str = "Anisha",
    style: str = "Conversation",
    min_sentence_len: int = 1,
    text_pacing: bool = True,
) -> murf.TTS | None:
    """Cached factory helper to instantiate or reuse Murf Falcon TTS with consistent streaming parameters."""
    cache_key = f"{voice}:{style}:{min_sentence_len}:{text_pacing}"
    if cache_key not in _TTS_CACHE:
        try:
            _TTS_CACHE[cache_key] = murf.TTS(
                voice=voice,
                style=style,
                tokenizer=tokenize.basic.SentenceTokenizer(
                    min_sentence_len=min_sentence_len
                ),
                text_pacing=text_pacing,
            )
        except Exception as e:
            logger.warning(f"Could not create Murf TTS for voice '{voice}': {e}")
            return None
    return _TTS_CACHE.get(cache_key)


class Assistant(Agent):
    """BolBuddy: Main Voice AI English speaking companion (Murf voice: 'Anisha')."""

    def __init__(
        self,
        chat_ctx: llm.ChatContext | None = None,
        tts: tts.TTS | str | None = None,
        voice: str = "Anisha",
        is_handoff_return: bool = False,
        **kwargs,
    ) -> None:
        agent_tts = tts
        if agent_tts is None and voice:
            try:
                agent_tts = create_murf_tts(voice=voice)
            except Exception as e:
                logger.warning(f"Could not create Murf TTS for voice '{voice}': {e}")
                agent_tts = None

        super().__init__(
            instructions=SYSTEM_PROMPT,
            chat_ctx=chat_ctx,
            tts=agent_tts if agent_tts is not None else NOT_GIVEN,
            **kwargs,
        )
        self._is_handoff_return = is_handoff_return

    async def on_enter(self) -> None:
        """When returning to BolBuddy from a specialist agent, greet immediately with zero LLM latency."""
        logger.info("BolBuddy entered active session")
        try:
            # 1. Update WebRTC room attributes
            if hasattr(self, "session") and self.session:
                try:
                    room = getattr(self.session, "room_io", None)
                    if room and hasattr(room, "room") and room.room:
                        local_p = room.room.local_participant
                        if local_p:
                            await local_p.set_attributes({
                                "active_agent": "bolbuddy",
                                "agent_name": "BolBuddy",
                                "agent_voice": "Anisha",
                            })
                except Exception as attr_err:
                    logger.info(f"Could not set participant attributes: {attr_err}")

                # 2. Greet returning user
                if self._is_handoff_return:
                    self.session.say(
                        "Welcome back! What would you like to practice next?",
                        allow_interruptions=True,
                    )
        except Exception as e:
            logger.error(f"Error in BolBuddy on_enter: {e}", exc_info=True)

    @function_tool
    async def lookup_user_memory(
        self,
        context: RunContext,
        user_id: str = "",
    ) -> str:
        """Look up saved user memory facts. Use only when needed to retrieve saved memory."""
        logger.info("TOOL CALL: lookup_user_memory")
        res = await fn_lookup_user_memory(context, user_id=user_id)
        logger.info("TOOL COMPLETE: lookup_user_memory")
        return res

    @function_tool
    async def save_user_memory(
        self,
        context: RunContext,
        name: str = "",
        language_preference: str = "",
        level: str = "",
        learning_goal: str = "",
        topic_practiced: str = "",
        recurring_challenge: str = "",
        user_id: str = "",
    ) -> str:
        """Save user memory facts (name, level, goal, challenge)."""
        logger.info(
            f"TOOL CALL: save_user_memory (name='{name}', goal='{learning_goal}')"
        )
        res = await fn_save_user_memory(
            context,
            name=name,
            language_preference=language_preference,
            level=level,
            learning_goal=learning_goal,
            topic_practiced=topic_practiced,
            recurring_challenge=recurring_challenge,
            user_id=user_id,
        )
        logger.info(f"TOOL COMPLETE: save_user_memory -> {res}")
        return res

    @function_tool
    async def forget_my_data(
        self,
        context: RunContext,
        user_id: str = "",
    ) -> str:
        """Delete saved user memory after explicit user confirmation."""
        logger.info(f"TOOL CALL: forget_my_data (user_id='{user_id}')")
        res = await fn_forget_my_data(context, user_id=user_id)
        logger.info(f"TOOL COMPLETE: forget_my_data -> {res}")
        return res

    @function_tool
    async def what_do_you_remember(
        self,
        context: RunContext,
        user_id: str = "",
    ) -> str:
        """Summarize saved user memory. Use only when user explicitly asks what is remembered."""
        logger.info(f"TOOL CALL: what_do_you_remember (user_id='{user_id}')")
        res = await fn_what_do_you_remember(context, user_id=user_id)
        logger.info("TOOL COMPLETE: what_do_you_remember")
        return res

    @function_tool
    async def search_learning_resources(
        self,
        context: RunContext,
        query: str = "",
    ) -> str:
        """Search learning resources for grammar rules, viva tips, or interview prep."""
        logger.info(f"TOOL CALL: search_learning_resources (query='{query}')")
        res = await fn_search_learning_resources(context, query=query)
        logger.info("TOOL COMPLETE: search_learning_resources")
        return res

    @function_tool
    async def fetch_next_exercise(
        self,
        context: RunContext,
        level: str = "beginner",
        topic: str = "interview",
    ) -> str:
        """Return one speaking exercise for requested level and topic. Use only when learner requests practice or a new exercise."""
        logger.info(
            f"TOOL CALL: fetch_next_exercise (level='{level}', topic='{topic}')"
        )
        res_dict = fn_get_next_exercise(level=level, topic=topic)
        import json

        res_str = json.dumps(res_dict)

        # Mark call outcome as success upon exercise selection
        try:
            call_id = None
            if hasattr(context, "proc") and hasattr(context.proc, "userdata"):
                call_id = context.proc.userdata.get("call_id")
            elif (
                hasattr(context, "session")
                and hasattr(context.session, "proc")
                and hasattr(context.session.proc, "userdata")
            ):
                call_id = context.session.proc.userdata.get("call_id")

            if call_id:
                mark_call_outcome(
                    call_id=call_id,
                    outcome="success",
                    reason=f"Selected exercise: {topic} ({level})",
                )
        except Exception as err:
            logger.warning(f"Failed to mark call outcome: {err}")

        logger.info(f"TOOL COMPLETE: fetch_next_exercise -> {res_str}")
        return res_str

    @function_tool
    async def score_spoken_answer(
        self,
        context: RunContext,
        exercise_question: str = "",
        user_spoken_answer: str = "",
        target_criteria: str = "grammar, clarity, confidence",
    ) -> str:
        """Evaluate a spoken practice answer. Return score, strengths, improvements, and encouragement."""
        logger.info("TOOL CALL: score_spoken_answer")
        res_dict = fn_score_spoken_answer(
            exercise_question=exercise_question,
            user_spoken_answer=user_spoken_answer,
            target_criteria=target_criteria,
        )
        import json

        res_str = json.dumps(res_dict)
        logger.info(f"TOOL COMPLETE: score_spoken_answer -> {res_str}")
        return res_str

    @function_tool
    async def mark_call_outcome(
        self,
        context: RunContext,
        outcome: str = "success",
        reason: str = "",
    ) -> str:
        """Mark the learning outcome of the active call session (success or failed). Call when learner completes a practice activity or interview exercise."""
        logger.info(
            f"TOOL CALL: mark_call_outcome (outcome='{outcome}', reason='{reason}')"
        )
        try:
            call_id = (
                context.proc.userdata.get("call_id")
                if hasattr(context, "proc") and hasattr(context.proc, "userdata")
                else None
            )
            if call_id:
                inc = 1 if outcome == "success" else 0
                res = mark_call_outcome(
                    call_id=call_id,
                    outcome=outcome,
                    failure_reason=reason or None,
                    completed_activities_inc=inc,
                )
                return f"Call outcome recorded as {res.get('outcome', outcome)}."
        except Exception as e:
            logger.warning(f"Error in mark_call_outcome tool: {e}")
        return f"Call outcome updated to {outcome}."

    @function_tool
    async def end_call(
        self,
        context: RunContext,
        reason: str = "DECLINED",
    ) -> str:
        """End the outbound call session cleanly after user declines or asks to disconnect."""
        logger.info(f"TOOL CALL: end_call (reason='{reason}')")
        try:
            sess = getattr(context, "session", None)
            if sess:
                room_io = getattr(sess, "room_io", None)
                if room_io and hasattr(room_io, "room") and room_io.room:

                    async def _disconnect_delay():
                        await asyncio.sleep(2.5)
                        try:
                            await room_io.room.disconnect()
                        except Exception as disc_err:
                            logger.warning(f"Disconnect error: {disc_err}")

                    disc_task = asyncio.create_task(_disconnect_delay())
                    if hasattr(sess, "userdata") and isinstance(sess.userdata, dict):
                        sess.userdata["disc_task"] = disc_task
        except Exception as e:
            logger.warning(f"Failed to schedule room disconnect: {e}")
        return f"Call ended gracefully ({reason})."

    @function_tool
    async def create_escalation(
        self,
        context: RunContext,
        who_needs_help: str = "",
        reason_type: str = "general_support",
        issue_summary: str = "",
        checked_by_agent: bool = True,
        urgency: str = "medium",
        preferred_language: str = "English",
        preferred_contact: str = "Email",
        user_id: str = "",
    ) -> str:
        """Create human support escalation ticket. Call only after learner explicitly confirms consent."""
        logger.info(
            f"TOOL CALL: create_escalation (reason='{reason_type}', urgency='{urgency}')"
        )
        res = fn_create_escalation(
            context,
            who_needs_help=who_needs_help,
            reason_type=reason_type,
            issue_summary=issue_summary,
            checked_by_agent=checked_by_agent,
            urgency=urgency,
            preferred_language=preferred_language,
            preferred_contact=preferred_contact,
            user_id=user_id,
        )
        logger.info(f"TOOL COMPLETE: create_escalation -> {res}")
        return res

    @function_tool
    async def transfer_to_interview_buddy(
        self,
        context: RunContext,
        target_role: str = "",
        user_id: str = "",
    ) -> Agent:
        """Transfer the learner to InterviewBuddy for job interview preparation, mock interviews, and practice questions. Call this immediately when the learner requests interview practice (e.g. 'I want to practice for an interview', 'I have an interview next week') or confirms a switch to InterviewBuddy."""
        logger.info(
            f"TOOL CALL: transfer_to_interview_buddy (target_role='{target_role}')"
        )
        # 1. Anisha speaks first in her voice to acknowledge connecting
        try:
            if hasattr(self, "session") and self.session:
                speech = self.session.say(
                    "Connecting you with InterviewBuddy now!",
                    allow_interruptions=False,
                )
                await speech
        except Exception as e:
            logger.debug(f"Anisha transition speech notice: {e}")

        copied_ctx = _clean_and_copy_chat_ctx(
            self.chat_ctx if hasattr(self, "chat_ctx") else None
        )
        interview_agent = InterviewBuddy(
            chat_ctx=copied_ctx,
            tts=create_murf_tts(voice="Samar"),
            voice="Samar",
            target_role=target_role,
        )
        logger.info(
            "TOOL COMPLETE: transfer_to_interview_buddy -> Handoff to InterviewBuddy (voice='Samar')"
        )
        return interview_agent


class InterviewBuddy(Agent):
    """InterviewBuddy: Specialist Voice Agent for job interview prep and mock interview practice (Murf voice: 'Samar')."""

    def __init__(
        self,
        chat_ctx: llm.ChatContext | None = None,
        tts: tts.TTS | str | None = None,
        voice: str = "Samar",
        target_role: str = "",
        **kwargs,
    ) -> None:
        agent_tts = tts
        if agent_tts is None and voice:
            try:
                agent_tts = create_murf_tts(voice=voice)
            except Exception as e:
                logger.warning(f"Could not create Murf TTS for voice '{voice}': {e}")
                agent_tts = None

        super().__init__(
            instructions=INTERVIEW_BUDDY_PROMPT,
            chat_ctx=chat_ctx,
            tts=agent_tts if agent_tts is not None else NOT_GIVEN,
            **kwargs,
        )
        self.target_role = target_role

    async def on_enter(self) -> None:
        """Immediately greet the learner upon handoff with zero LLM roundtrip latency."""
        logger.info("InterviewBuddy entered active session")
        try:
            # 1. Update WebRTC room attributes
            if hasattr(self, "session") and self.session:
                try:
                    room = getattr(self.session, "room_io", None)
                    if room and hasattr(room, "room") and room.room:
                        local_p = room.room.local_participant
                        if local_p:
                            await local_p.set_attributes({
                                "active_agent": "interview_buddy",
                                "agent_name": "InterviewBuddy",
                                "agent_voice": "Samar",
                            })
                except Exception as attr_err:
                    logger.info(f"Could not set participant attributes: {attr_err}")

                # 2. Samar greets the learner and asks the first interview question
                if self.target_role:
                    greeting = f"Hi, I'm InterviewBuddy! Let's practice for {self.target_role}. Tell me about yourself."
                else:
                    greeting = "Hi, I'm InterviewBuddy! What role are you preparing for?"

                logger.info(f"InterviewBuddy speaking initial greeting: '{greeting}'")
                self.session.say(greeting, allow_interruptions=True)
        except Exception as e:
            logger.error(f"Error in InterviewBuddy on_enter: {e}", exc_info=True)

    @function_tool
    async def score_spoken_answer(
        self,
        context: RunContext,
        exercise_question: str = "",
        user_spoken_answer: str = "",
        target_criteria: str = "grammar, clarity, confidence",
    ) -> str:
        """Evaluate a spoken interview answer. Return score, strengths, improvements, and encouragement."""
        logger.info("TOOL CALL: score_spoken_answer (InterviewBuddy)")
        res_dict = fn_score_spoken_answer(
            exercise_question=exercise_question,
            user_spoken_answer=user_spoken_answer,
            target_criteria=target_criteria,
        )
        import json

        res_str = json.dumps(res_dict)
        logger.info(f"TOOL COMPLETE: score_spoken_answer -> {res_str}")
        return res_str

    @function_tool
    async def create_escalation(
        self,
        context: RunContext,
        who_needs_help: str = "",
        reason_type: str = "general_support",
        issue_summary: str = "",
        checked_by_agent: bool = True,
        urgency: str = "medium",
        preferred_language: str = "English",
        preferred_contact: str = "Email",
        user_id: str = "",
    ) -> str:
        """Create human support escalation ticket. Call only after learner explicitly confirms consent."""
        logger.info(
            f"TOOL CALL: create_escalation (reason='{reason_type}', urgency='{urgency}')"
        )
        res = fn_create_escalation(
            context,
            who_needs_help=who_needs_help,
            reason_type=reason_type,
            issue_summary=issue_summary,
            checked_by_agent=checked_by_agent,
            urgency=urgency,
            preferred_language=preferred_language,
            preferred_contact=preferred_contact,
            user_id=user_id,
        )
        logger.info(f"TOOL COMPLETE: create_escalation -> {res}")
        return res

    @function_tool
    async def transfer_to_bolbuddy(
        self,
        context: RunContext,
        reason: str = "",
        user_id: str = "",
    ) -> Agent:
        """Transfer the learner back to BolBuddy whenever the conversation moves outside of job interview preparation, or the learner asks general English/grammar questions, makes small talk/casual conversation, or finishes interview practice."""
        logger.info(f"TOOL CALL: transfer_to_bolbuddy (reason='{reason}')")
        # 1. Samar speaks first in his voice to acknowledge handback
        try:
            if hasattr(self, "session") and self.session:
                speech = self.session.say(
                    "Of course! Handing you back to BolBuddy.",
                    allow_interruptions=False,
                )
                await speech
        except Exception as e:
            logger.debug(f"Samar transition speech notice: {e}")

        copied_ctx = _clean_and_copy_chat_ctx(
            self.chat_ctx if hasattr(self, "chat_ctx") else None
        )
        bolbuddy_agent = Assistant(
            chat_ctx=copied_ctx,
            tts=create_murf_tts(voice="Anisha"),
            voice="Anisha",
            is_handoff_return=True,
        )
        logger.info(
            "TOOL COMPLETE: transfer_to_bolbuddy -> switching back to BolBuddy (voice='Anisha')"
        )
        return bolbuddy_agent


def _prune_history(session: AgentSession, max_turns: int = 6) -> None:
    """Keep chat context history trimmed to prevent context window token bloat and reduce LLM response latency."""
    try:
        hist = getattr(session, "history", None) or getattr(session, "chat_ctx", None)
        if hist and hasattr(hist, "truncate"):
            hist.truncate(max_items=max_turns)
            logger.info("Pruned chat context history to prevent token bloat.")
        elif hist and hasattr(hist, "messages"):
            msgs = hist.messages
            if len(msgs) > max_turns + 1:
                system_msg = (
                    [msgs[0]]
                    if (
                        msgs
                        and getattr(msgs[0], "role", None) in ("system", "developer")
                    )
                    else []
                )
                recent_msgs = msgs[-max_turns:]
                hist.messages = system_msg + [
                    m for m in recent_msgs if m not in system_msg
                ]
                logger.info(f"Pruned chat history to {len(hist.messages)} messages.")
    except Exception as e:
        logger.warning(f"Failed to prune chat history: {e}")


def _clean_tts_text(text: str) -> str:
    """Sanitize spoken text output to ensure no raw tool tags, XML, or JSON reach TTS audio synthesis."""
    if not text:
        return ""
    import re

    # 1. Remove XML/function tags e.g. </function>, <function=...>, <tool_call...>, </tool_call>
    text = re.sub(
        r"</?(?:function|tool_call|tool)[^>]*>", "", text, flags=re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", "", text)

    # 2. Remove raw function syntax e.g. fetch_next_exercise>{"level": ...} or tool_name>{...}
    text = re.sub(r"\b\w+>\{[\s\S]*?\}", "", text)
    text = re.sub(r"\b\w+>\{[\s\S]*", "", text)

    # 3. Remove any JSON structures or raw parameter dictionaries (complete OR unclosed)
    text = re.sub(
        r"\{\s*\"(?:name|parameters|level|topic|who_needs_help|reason_type|issue_summary|checked_by_agent|urgency|preferred_language|preferred_contact|user_id)\"[\s\S]*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\{[\s\S]*?\}", "", text)

    # 4. Remove raw function calls e.g. create_escalation(...), fetch_next_exercise>...
    text = re.sub(
        r"\b(?:create_escalation|score_spoken_answer|fetch_next_exercise|lookup_user_memory|save_user_memory|forget_my_data|what_do_you_remember|search_learning_resources|mark_call_outcome)\b[>\s\S]*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b\w+_\w+\([^)]*\)", "", text)
    text = re.sub(r"function\s*[:=]?\s*\w+", "", text, flags=re.IGNORECASE)

    # 5. Strip markdown formatting symbols
    text = re.sub(r"[`*_~#]", "", text)
    return re.sub(r"\s+", " ", text).strip()


server = AgentServer(job_executor_type=JobExecutorType.THREAD)


def prewarm(proc: JobProcess):
    # Responsive noise-resilient VAD tuned to avoid stuck-in-listening states
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=0.1,
        min_silence_duration=0.2,
        prefix_padding_duration=0.2,
        activation_threshold=0.3,
    )
    init_db()

    # Start persistent background daily practice scheduler
    try:
        from scheduler import start_scheduler_loop

        sched_task = asyncio.create_task(start_scheduler_loop())
        proc.userdata["sched_task"] = sched_task
    except Exception as sched_err:
        logger.warning(f"Could not start background scheduler: {sched_err}")


server.setup_fnc = prewarm


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    # Logging setup
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # LLM Initialization: Multi-provider support (OpenRouter -> NVIDIA -> Groq -> Google Gemini)
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    google_key = os.getenv("GOOGLE_API_KEY", "").strip()

    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1000"))

    if provider == "openrouter" or (not provider and openrouter_key):
        openrouter_model = os.getenv(
            "OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct"
        ).strip()
        logger.info(f"LLM Provider: OpenRouter ({openrouter_model}) [max_tokens={max_tokens}]")
        llm = openai.LLM(
            model=openrouter_model,
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_key,
            temperature=0.7,
            max_completion_tokens=max_tokens,
            parallel_tool_calls=False,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
        )
    elif provider == "nvidia" or (not provider and nvidia_key):
        nvidia_model = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct").strip()
        nvidia_base_url = os.getenv(
            "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
        ).strip()
        logger.info(f"LLM Provider: NVIDIA API ({nvidia_model}) [max_tokens={max_tokens}]")
        llm = openai.LLM(
            model=nvidia_model,
            base_url=nvidia_base_url,
            api_key=nvidia_key,
            temperature=0.7,
            top_p=1.0,
            max_completion_tokens=max_tokens,
            parallel_tool_calls=False,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
        )
    elif provider == "groq" or (not provider and groq_key):
        groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip()
        logger.info(f"LLM Provider: Groq API ({groq_model}) [max_tokens={max_tokens}]")
        llm = openai.LLM(
            model=groq_model,
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            temperature=0.7,
            max_completion_tokens=max_tokens,
            parallel_tool_calls=False,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
        )
    elif provider == "google" or (not provider and google_key):
        logger.info("LLM Provider: Google Gemini (gemini-2.0-flash)")
        llm = google.LLM(model="gemini-2.0-flash")
    else:
        raise ValueError(
            "No valid LLM API key (OpenRouter, NVIDIA, Groq, or Google) found in environment."
        )

    # Built-in text transforms to strip markdown and emojis from spoken audio
    tts_transforms = ["filter_markdown", "filter_emoji"]

    # Text-to-speech (TTS) via Murf Falcon (min_sentence_len=1 for immediate audio streaming)
    tts_anisha = create_murf_tts(voice="Anisha")
    tts_samar = create_murf_tts(voice="Samar")

    async def _prewarm_tts_connections():
        try:
            if tts_anisha and hasattr(tts_anisha, "prewarm"):
                tts_anisha.prewarm()
            if tts_samar and hasattr(tts_samar, "prewarm"):
                tts_samar.prewarm()
        except Exception as prewarm_err:
            logger.info(f"TTS connection prewarm info: {prewarm_err}")

    _prewarm_task = asyncio.create_task(_prewarm_tts_connections())
    # Keep reference on proc userdata to prevent early GC
    ctx.proc.userdata["prewarm_task"] = _prewarm_task

    # Set up a voice AI pipeline matching official Murf multilingual recommendation
    session_kwargs = {
        # Speech-to-text (STT) via Deepgram Nova-3 with multilingual support (en + hi + hinglish)
        "stt": deepgram.STT(model="nova-3", language="multi", smart_format=True),
        # A Large Language Model (LLM) processing user input and executing function tools
        "llm": llm,
        "tts": tts_anisha,
        "vad": ctx.proc.userdata["vad"],
        # Responsive endpointing delays (0.15s silence threshold, 0.5s max phrase window)
        "min_endpointing_delay": 0.15,
        "max_endpointing_delay": 0.5,
        # Preemptive generation for faster turn-taking
        "preemptive_generation": True,
        "tts_text_transforms": tts_transforms,
        "user_away_timeout": 8.0,
    }

    session = AgentSession(**session_kwargs)

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev):
        if getattr(ev, "is_final", False):
            _prune_history(session, max_turns=6)
            logger.info("USER TURN COMMITTED")
            logger.info("LLM GENERATION STARTING...")

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev):
        new_state = getattr(ev, "new_state", "")
        old_state = getattr(ev, "old_state", "")
        if new_state == "speaking":
            logger.info("LLM GENERATION COMPLETE -> MURF TTS STARTING...")
        elif old_state == "speaking" and new_state == "listening":
            logger.info("MURF TTS AUDIO PLAYBACK COMPLETE")

    @session.on("user_state_changed")
    def _on_user_state_changed(ev):
        new_state = getattr(ev, "new_state", "")
        if new_state == "away":
            logger.info(
                "USER SILENT (8s timeout) -> Auto-generating conversation continuation prompt"
            )
            session.generate_reply(
                instructions="The learner has been quiet for a few seconds. Gently check in and ask an encouraging question to keep the English practice conversation flowing."
            )

    # Attach event listener for TPM rate-limit exception handling
    @session.on("error")
    def _on_session_error(err):
        err_str = str(err).lower()
        if "429" in err_str or "tpm" in err_str or "rate limit" in err_str:
            logger.error(f"LLM API rate limit error detected: {err}")

            async def _speak_error():
                try:
                    await session.say(
                        "I'm a little busy right now. Give me a few seconds and try again.",
                        allow_interruptions=True,
                    )
                except Exception as say_err:
                    logger.warning(f"Error speaking rate limit message: {say_err}")

            err_task = asyncio.create_task(_speak_error())
            ctx.proc.userdata["err_task"] = err_task

    # Join the room and connect to the user first
    await ctx.connect()

    # Start the session, which initializes the voice pipeline and warms up the models
    session_started = asyncio.create_task(
        session.start(
            agent=Assistant(),
            room=ctx.room,
        )
    )
    ctx.proc.userdata["session_task"] = session_started

    # Set initial participant attributes on the agent
    if ctx.room and ctx.room.local_participant:
        try:
            await ctx.room.local_participant.set_attributes({
                "active_agent": "bolbuddy",
                "agent_name": "BolBuddy",
                "agent_voice": "Anisha",
            })
        except Exception as attr_err:
            logger.info(f"Initial participant attributes: {attr_err}")

    # Track user interaction and deliver initial personalized voice greeting
    try:
        participant = await ctx.wait_for_participant()
        user_id = (
            participant.identity
            if participant and participant.identity
            else "default_user"
        )
        user_data = get_or_create_user(user_id=user_id)
        ctx.proc.userdata["user_id"] = user_id

        # Launch non-blocking background task to pre-fetch memory cache
        prefetch_task = asyncio.create_task(async_prefetch_user_memory(user_id))
        ctx.proc.userdata["prefetch_task"] = prefetch_task

        # Check if room or participant represents an outbound call session
        is_outbound = False
        if (
            ctx.room
            and ctx.room.name
            and ("outbound" in ctx.room.name.lower() or "sip" in ctx.room.name.lower())
        ):
            is_outbound = True
        if (
            participant
            and getattr(participant, "attributes", None)
            and participant.attributes.get("is_outbound") == "true"
        ):
            is_outbound = True

        call_id = ctx.room.name if (ctx.room and ctx.room.name) else f"call_{user_id}"
        channel = "sip" if is_outbound else "browser"
        record_call_start(call_id=call_id, user_id=user_id, channel=channel)
        ctx.proc.userdata["call_id"] = call_id

        name = user_data.get("name") if user_data else None
        facts = user_data.get("facts") if user_data else {}
        goal = facts.get("learning_goal") if facts else None

        if is_outbound:
            if name:
                greeting_text = f"Hi {name}, this is BolBuddy, your English practice companion. You scheduled your daily practice call for this time. If you'd rather not practice now, just say so and I'll end the call. Want to practice for a few minutes?"
            else:
                greeting_text = "Hi, this is BolBuddy, your English practice companion. You scheduled your daily practice call for this time. If you'd rather not practice now, just say so and I'll end the call. Want to practice for a few minutes?"
        elif name:
            greeting_text = f"Welcome back {name}! It's great to see you again. What would you like to practice today?"
        elif goal and goal != "everyday conversation":
            greeting_text = f"Hello! Ready to practice your {goal} today?"
        else:
            greeting_text = "Welcome! I'm BolBuddy, your English speaking companion. What's your name, and what would you like to practice today?"

        async def _deliver_greeting():
            try:
                await asyncio.sleep(0.3)
                await session.say(
                    _clean_tts_text(greeting_text), allow_interruptions=True
                )
            except (Exception, asyncio.CancelledError) as e:
                logger.info(f"Initial greeting delivery ended or cancelled: {e}")

        greeting_task = asyncio.create_task(_deliver_greeting())
        ctx.proc.userdata["greeting_task"] = greeting_task
    except (Exception, asyncio.CancelledError) as err:
        logger.info(f"Participant greeting setup skipped: {err}")

    # Keep agent entrypoint active until session completes
    try:
        await session_started
    finally:
        active_call_id = ctx.proc.userdata.get("call_id")
        if active_call_id:
            finalize_call(
                call_id=active_call_id,
                default_outcome="success",
                default_reason=None,
            )


if __name__ == "__main__":
    cli.run_app(server)
