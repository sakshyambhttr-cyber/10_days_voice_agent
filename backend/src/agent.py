# ruff: noqa: E402
import asyncio
import json
import logging
import os
import re

import httpx
from dotenv import load_dotenv

# Ensure environment variables from backend/.env.local are eagerly loaded
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_backend_dir, ".env.local"))
load_dotenv(os.path.join(_backend_dir, ".env"))
load_dotenv(".env.local")
load_dotenv()

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
    _compute_score,
    score_spoken_answer as fn_score_spoken_answer,
)

logger = logging.getLogger("agent")


def _prune_history(session: AgentSession, max_turns: int = 6) -> None:
    """Keep system prompt + most recent max_turns messages and filter out raw function JSON leakage."""
    try:
        if (
            hasattr(session, "chat_ctx")
            and session.chat_ctx
            and hasattr(session.chat_ctx, "messages")
        ):
            msgs = session.chat_ctx.messages
            cleaned_msgs = []
            for m in msgs:
                content = str(getattr(m, "content", "") or "")
                if (
                    '{"name":' in content
                    or '{"who_needs_help"' in content
                    or '"parameters":' in content
                    or "</function>" in content
                    or "<tool_call>" in content
                    or "create_escalation" in content
                    or "fetch_next_exercise" in content
                    or "score_spoken_answer" in content
                    or (">" in content and "{" in content)
                ):
                    clean_content = re.sub(r"\b\w+>\s*\{[^}]*\}?", "", content)
                    clean_content = re.sub(
                        r"<\/?(?:tool_call|function)[^>]*>", "", clean_content
                    )
                    clean_content = re.sub(
                        r"\{\s*\"[^\"]+\"\s*:[\s\S]*?\}", "", clean_content
                    ).strip()
                    if not clean_content or clean_content.startswith("{"):
                        continue
                    if hasattr(m, "content"):
                        m.content = clean_content
                cleaned_msgs.append(m)

            if len(cleaned_msgs) > max_turns + 1:
                system_msg = (
                    [cleaned_msgs[0]]
                    if (
                        cleaned_msgs
                        and getattr(cleaned_msgs[0], "role", None)
                        in ("system", "developer")
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


def _clean_tts_text(text: str) -> str:
    """Sanitize spoken text output to ensure no raw tool tags, XML, JSON, or formatting noise reach TTS audio synthesis."""
    if not text:
        return ""

    # 1. Remove pseudo tool calls like fetch_next_exercise>{...} or tool_name>{...}
    text = re.sub(r"\b\w+>\s*\{[^}]*\}?", "", text)
    text = re.sub(
        r"\(?\s*function\s*=\s*\w+[^>)]*[\)>]?", "", text, flags=re.IGNORECASE
    )
    text = re.sub(
        r"</?(?:function|tool_call|tool)[^>]*>", "", text, flags=re.IGNORECASE
    )
    text = re.sub(r"\(?\s*function[\s\S]*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)

    # 2. Remove any JSON structures or raw parameter dictionaries (complete OR unclosed)
    text = re.sub(
        r"\{\s*\"(?:name|parameters|level|topic|who_needs_help|reason_type|issue_summary|checked_by_agent|preferred_language|preferred_contact|user_id|reference_id|key|value|category|query|exercise_question|user_spoken_answer|target_criteria)\"[\s\S]*?\}",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\{\s*\"[^\"]+\"\s*:[\s\S]*?\}", "", text)
    text = re.sub(r"\{[\s\S]*?\}", "", text)

    # 3. Strip markdown formatting symbols and unwanted characters
    text = re.sub(r"[\/\\\_\|\#\*\=\+\@\%\^\&\~\`]+", " ", text)
    text = re.sub(r"\.{2,}", ".", text)
    return re.sub(r"\s+", " ", text).strip()


def create_murf_tts(voice: str = "Anisha") -> murf.TTS:
    """Create Murf Falcon streaming TTS instance with specified voice."""
    return murf.TTS(
        voice=voice,
        style="Conversation",
        tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=1),
        text_pacing=True,
    )


# ---------------------------------------------------------------------------
# MAIN AGENT: BolBuddy (Murf Falcon · Anisha)
# ---------------------------------------------------------------------------
class Assistant(Agent):
    """
    BolBuddy — General English Speaking Companion.
    Handles general English conversation, pronunciation, vocabulary, memory, practice exercises,
    and transfers to InterviewBuddy when the user requests job interview or mock interview practice.
    """

    def __init__(
        self,
        chat_ctx: llm.ChatContext | None = None,
        tts: tts.TTS | str | None = None,
        voice: str = "Anisha",
        is_handoff_return: bool = False,
        **kwargs,
    ) -> None:
        agent_tts = tts
        if agent_tts is None or isinstance(agent_tts, str):
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
        self.voice = voice

    async def on_enter(self) -> None:
        logger.info(f"Entering BolBuddy (voice: Murf Falcon · {self.voice})")
        try:
            if (
                hasattr(self, "session")
                and self.session
                and hasattr(self.session, "room_io")
            ):
                room = getattr(self.session.room_io, "room", None)
                if (
                    room
                    and hasattr(room, "local_participant")
                    and room.local_participant
                ):
                    await room.local_participant.set_attributes(
                        {
                            "active_agent": "bolbuddy",
                            "agent_name": "BolBuddy",
                            "agent_title": "English Speaking Companion",
                            "voice_name": "Murf Falcon · Anisha",
                        }
                    )
        except Exception as e:
            logger.debug(f"Attribute update notice: {e}")

        if getattr(self, "_is_handoff_return", False):
            try:
                if hasattr(self, "session") and self.session:
                    await self.session.say(
                        "Welcome back! What would you like to practice?",
                        allow_interruptions=True,
                    )
            except Exception as e:
                logger.debug(f"BolBuddy return greeting trigger notice: {e}")

    @function_tool
    async def transfer_to_interview_buddy(
        self,
        context: RunContext,
        reason: str = "interview_preparation",
        target_role: str = "software internship",
    ) -> Agent:
        """
        Transfer the conversation to InterviewBuddy, the job interview preparation specialist.
        CRITICAL: ONLY invoke this tool AFTER the user explicitly agrees/confirms to be connected with InterviewBuddy.
        DO NOT invoke if the user has not confirmed or declined.
        """
        logger.info(
            f"TOOL CALL: transfer_to_interview_buddy (reason='{reason}', target_role='{target_role}')"
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

        # 2. Switch to InterviewBuddy in Samar's voice
        chat_ctx = self.chat_ctx.copy(exclude_instructions=True)
        specialist = InterviewBuddy(
            chat_ctx=chat_ctx,
            tts=create_murf_tts(voice="Samar"),
            voice="Samar",
            target_role=target_role or "software internship",
        )
        logger.info(
            "TOOL COMPLETE: transfer_to_interview_buddy -> switching to InterviewBuddy (voice='Samar')"
        )
        return specialist

    @function_tool
    async def lookup_user_memory(
        self,
        context: RunContext,
        user_id: str = "",
    ) -> str:
        """Look up saved user memory facts for a RETURNING user who has previously introduced themselves. Call ONLY when resuming a known returning session. NEVER call on a first-time greeting like 'Hello' or 'Namaste'."""
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
        """Save user profile details only when the learner explicitly introduces their name or personal details. Do not invoke on general greetings or practice requests."""
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
        """Summarize saved user memory. Call ONLY when user explicitly says 'What do you remember about me?' or similar. NEVER call on greetings or emotional expressions."""
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
        """Search learning resources for curriculum topics, grammar rules, viva tips, or interview prep guides. Call ONLY when user explicitly asks for learning material or advanced grammar. NEVER call for emotional expressions, greetings, or casual conversation."""
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
        """Fetch a structured practice exercise only when the learner explicitly asks for a structured exercise, quiz, or test. Do not call for normal conversational speaking practice."""
        logger.info(
            f"TOOL CALL: fetch_next_exercise (level='{level}', topic='{topic}')"
        )
        res_dict = fn_get_next_exercise(level=level, topic=topic)
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
        """Evaluate learner's spoken answer ONLY to an explicit English practice exercise that was previously presented. NEVER call when the user says hello, introduces themselves, expresses emotions, speaks in Hindi/Hinglish, or has not been given an exercise question."""
        logger.info("TOOL CALL: score_spoken_answer")
        res_dict = _compute_score(user_spoken_answer or exercise_question)
        res_str = json.dumps(res_dict)
        logger.info(f"TOOL COMPLETE: score_spoken_answer -> {res_str}")
        return res_str

    async def mark_call_outcome(
        self,
        context: RunContext,
        outcome: str = "success",
        reason: str = "",
    ) -> str:
        """Internal helper to record call outcome."""
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

    async def end_call(
        self,
        context: RunContext,
        reason: str = "user_requested_hangup",
    ) -> str:
        """Internal helper to end call cleanly."""
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
        """Create human support escalation ticket. CRITICAL: NEVER call this tool on the first user message, on initial requests for a teacher, or when the user says no/declines. ONLY call this tool AFTER the learner explicitly says YES or gives clear consent to create a request."""
        logger.info(
            f"TOOL CALL: create_escalation (reason='{reason_type}', urgency='{urgency}')"
        )
        res = await fn_create_escalation(
            context,
            who_needs_help=who_needs_help,
            reason_type=reason_type,
            issue_summary=issue_summary,
            checked_by_agent=str(checked_by_agent),
            urgency=urgency,
            preferred_language=preferred_language,
            preferred_contact=preferred_contact,
            user_id=user_id,
        )
        logger.info(f"TOOL COMPLETE: create_escalation -> {res}")
        return res


# ---------------------------------------------------------------------------
# SPECIALIST AGENT: InterviewBuddy (Murf Falcon · Samar)
# ---------------------------------------------------------------------------
class InterviewBuddy(Agent):
    """
    InterviewBuddy — Specialist Voice Agent for job interview prep, mock interviews,
    and spoken feedback (Murf Falcon voice: 'Samar').
    """

    def __init__(
        self,
        chat_ctx: llm.ChatContext | None = None,
        tts: tts.TTS | str | None = None,
        voice: str = "Samar",
        target_role: str = "",
        **kwargs,
    ) -> None:
        agent_tts = tts
        if agent_tts is None or isinstance(agent_tts, str):
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
        self.voice = voice

    async def on_enter(self) -> None:
        logger.info(f"Entering InterviewBuddy (voice: Murf Falcon · {self.voice})")
        try:
            if (
                hasattr(self, "session")
                and self.session
                and hasattr(self.session, "room_io")
            ):
                room = getattr(self.session.room_io, "room", None)
                if (
                    room
                    and hasattr(room, "local_participant")
                    and room.local_participant
                ):
                    await room.local_participant.set_attributes(
                        {
                            "active_agent": "interview_buddy",
                            "agent_name": "InterviewBuddy",
                            "agent_title": "Job Interview Specialist",
                            "voice_name": "Murf Falcon · Samar",
                        }
                    )
        except Exception as e:
            logger.debug(f"Attribute update notice: {e}")

        # Automatically greet the user upon handoff in Samar's voice
        try:
            if hasattr(self, "session") and self.session:
                if self.target_role:
                    greeting = f"Hi! I'm InterviewBuddy. I'll help you prepare for your interview. I already know that you have a {self.target_role} interview next week, so you don't need to repeat everything. Let's start with a common interview question: Tell me about yourself."
                else:
                    greeting = "Hi! I'm InterviewBuddy. I'll help you prepare for your interview. I already know that you have an interview coming up, so you don't need to repeat everything. Let's start with a common interview question: Tell me about yourself."
                await self.session.say(greeting, allow_interruptions=True)
        except Exception as e:
            logger.debug(f"InterviewBuddy greeting trigger notice: {e}")

    @function_tool
    async def score_spoken_answer(
        self,
        context: RunContext,
        exercise_question: str = "",
        user_spoken_answer: str = "",
        target_criteria: str = "grammar, clarity, confidence",
    ) -> str:
        """Evaluate a spoken practice answer. Return score, strengths, improvements, and encouragement."""
        logger.info("TOOL CALL: score_spoken_answer (InterviewBuddy)")
        res_dict = _compute_score(user_spoken_answer or exercise_question)
        res_str = json.dumps(res_dict)
        logger.info(f"TOOL COMPLETE: score_spoken_answer -> {res_str}")
        return res_str

    @function_tool
    async def search_learning_resources(
        self,
        context: RunContext,
        query: str = "",
    ) -> str:
        """Search learning resources for interview tips, common questions, or preparation guidance."""
        logger.info(
            f"TOOL CALL: search_learning_resources (InterviewBuddy query='{query}')"
        )
        res = await fn_search_learning_resources(context, query=query)
        logger.info("TOOL COMPLETE: search_learning_resources (InterviewBuddy)")
        return res

    @function_tool
    async def fetch_next_exercise(
        self,
        context: RunContext,
        level: str = "intermediate",
        topic: str = "interview",
    ) -> str:
        """Return one interview speaking exercise or question."""
        logger.info(
            f"TOOL CALL: fetch_next_exercise (InterviewBuddy level='{level}', topic='{topic}')"
        )
        res_dict = fn_get_next_exercise(level=level, topic=topic)
        return json.dumps(res_dict)

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
        """Create human support escalation ticket if requested while in InterviewBuddy."""
        logger.info(
            f"TOOL CALL: create_escalation (InterviewBuddy reason='{reason_type}', urgency='{urgency}')"
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
        logger.info(f"TOOL COMPLETE: create_escalation (InterviewBuddy) -> {res}")
        return res

    @function_tool
    async def transfer_to_bolbuddy(
        self,
        context: RunContext,
        reason: str = "general_conversation",
        user_id: str = "",
    ) -> Agent:
        """Transfer back to BolBuddy whenever the conversation moves outside of job interview preparation, or the learner asks general English/grammar questions, makes small talk/casual conversation, or finishes interview practice."""
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

        # 2. Switch to BolBuddy in Anisha's voice
        chat_ctx = self.chat_ctx.copy(exclude_instructions=True)
        main_agent = Assistant(
            chat_ctx=chat_ctx,
            tts=create_murf_tts(voice="Anisha"),
            voice="Anisha",
            is_handoff_return=True,
        )
        logger.info(
            "TOOL COMPLETE: transfer_to_bolbuddy -> switching back to BolBuddy (voice='Anisha')"
        )
        return main_agent


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
        "room": ctx.room.name if ctx.room and ctx.room.name else "unknown_room",
    }

    # LLM Initialization: Multi-provider support (OpenRouter -> NVIDIA -> Groq -> Google Gemini)
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    google_key = os.getenv("GOOGLE_API_KEY", "").strip()

    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1000"))

    try:
        if provider == "openrouter" or (not provider and openrouter_key):
            openrouter_model = os.getenv(
                "OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct"
            ).strip()
            logger.info(f"LLM Provider: OpenRouter ({openrouter_model}) [max_tokens={max_tokens}]")
            llm_inst = openai.LLM(
                model=openrouter_model,
                base_url="https://openrouter.ai/api/v1",
                api_key=openrouter_key,
                temperature=0.3,
                max_completion_tokens=max_tokens,
                parallel_tool_calls=False,
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
            )
        elif provider == "nvidia" or (not provider and nvidia_key):
            nvidia_model = os.getenv(
                "NVIDIA_MODEL", "meta/llama-3.1-8b-instruct"
            ).strip()
            nvidia_base_url = os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ).strip()
            logger.info(f"LLM Provider: NVIDIA API ({nvidia_model}) [max_tokens={max_tokens}]")
            llm_inst = openai.LLM(
                model=nvidia_model,
                base_url=nvidia_base_url,
                api_key=nvidia_key,
                temperature=0.3,
                top_p=1.0,
                max_completion_tokens=max_tokens,
                parallel_tool_calls=False,
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
            )
        elif provider == "groq" or (not provider and groq_key):
            groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip()
            logger.info(f"LLM Provider: Groq API ({groq_model}) [max_tokens={max_tokens}]")
            llm_inst = openai.LLM(
                model=groq_model,
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_key,
                temperature=0.3,
                max_completion_tokens=max_tokens,
                parallel_tool_calls=False,
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
            )
        elif provider == "google" or (not provider and google_key):
            logger.info("LLM Provider: Google Gemini (gemini-2.0-flash)")
            llm_inst = google.LLM(model="gemini-2.0-flash")
        else:
            raise ValueError(
                "No valid LLM API key (OpenRouter, NVIDIA, Groq, or Google) found in environment."
            )
    except Exception as llm_init_err:
        logger.warning(
            f"Failed to initialize primary LLM provider '{provider}': {llm_init_err}. Attempting fallback provider..."
        )
        if google_key:
            logger.info("Fallback LLM Provider: Google Gemini (gemini-2.0-flash)")
            llm_inst = google.LLM(model="gemini-2.0-flash")
        elif groq_key:
            logger.info(f"Fallback LLM Provider: Groq API (llama-3.1-8b-instant) [max_tokens={max_tokens}]")
            llm_inst = openai.LLM(
                model="llama-3.1-8b-instant",
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_key,
                temperature=0.7,
                max_completion_tokens=max_tokens,
                parallel_tool_calls=False,
            )
        else:
            raise llm_init_err

    # Built-in text transforms to strip markdown and emojis from spoken audio
    tts_transforms = ["filter_markdown", "filter_emoji"]

    # Set up a shared voice AI pipeline matching official Murf multilingual recommendation
    # Default TTS voice is Anisha (BolBuddy); specialist agent switches to Samar (InterviewBuddy)
    session_kwargs = {
        # Speech-to-text (STT) via Deepgram Nova-3 with multilingual support (en + hi + hinglish)
        "stt": deepgram.STT(model="nova-3", language="multi", smart_format=True),
        # Large Language Model (LLM) processing user input and executing function tools
        "llm": llm_inst,
        # Text-to-speech (TTS) via Murf Falcon (min_sentence_len=1 for immediate audio streaming)
        "tts": murf.TTS(
            voice="Anisha",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=1),
            text_pacing=True,
        ),
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
        _prune_history(session, max_turns=6)
        logger.info("USER TURN COMMITTED")
        logger.info("LLM GENERATION STARTING...")

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev):
        new_state = str(getattr(ev, "new_state", getattr(ev, "state", ev))).lower()
        old_state = str(getattr(ev, "old_state", "")).lower()
        if "speaking" in new_state:
            logger.info("LLM GENERATION COMPLETE -> MURF TTS STARTING...")
        elif "speaking" in old_state and "listening" in new_state:
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

    # Start the session with BolBuddy (Assistant) as default active agent
    session_started = asyncio.create_task(
        session.start(
            agent=Assistant(),
            room=ctx.room,
        )
    )
    ctx.proc.userdata["session_task"] = session_started

    # Track user interaction and deliver initial personalized voice greeting
    try:
        participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=5.0)
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
