# Day 9 — BolBuddy Specialist Agent Handoff (InterviewBuddy)

Welcome to **Day 9** of the **Murf 10 Days of Voice Agents** challenge for **BolBuddy** — your voice-first spoken English learning companion.

Day 9 introduces a seamless **Specialist Agent Handoff** architecture connecting **BolBuddy** (General English Conversation & Practice) with **InterviewBuddy** (Job Interview & Mock Interview Specialist) using standard LiveKit Agent handoff patterns powered by **Murf Falcon Indian Multilingual TTS**.

---

## 🌟 Key Highlights & Architecture

### 1. Main Agent & Specialist Agent Roles

| Agent | Murf Voice | Core Specialty | Typical Queries Handled |
| :--- | :--- | :--- | :--- |
| **BolBuddy** (Main Agent) | **Anisha** (Indian Multilingual Female) | General English practice, daily conversation, confidence building, vocabulary definitions, grammar explanations, pronunciation tips, casual chit-chat. | *"I want to practice English"*, *"What does confident mean?"*, *"Help me learn new vocabulary"*, *"How do I sound more natural?"* |
| **InterviewBuddy** (Specialist Agent) | **Samar** (Indian Multilingual Male) | Focused job interview preparation, mock interviews, standard & behavioral interview questions, concise feedback on spoken clarity, grammar, and answer structure. | *"I have a job interview next week"*, *"Can you ask me mock interview questions?"*, *"Let's practice behavioral questions for a software role"* |

---

### 2. Fast, Snappy & Intuitive Handoff Flow

- **Direct Intent Detection**: When the learner requests interview practice (e.g. *"I have a software interview next week and want to practice"*), BolBuddy immediately executes `transfer_to_interview_buddy` in **0.38s** with a single concise confirmation:
  > *"Connecting you with InterviewBuddy now for focused interview practice."*
- **No Conversational Stalling**: Handoff occurs without unnecessary multi-turn friction.
- **Handback Capability**: If the learner says *"Let's chat casually"* or *"Switch back to BolBuddy"*, InterviewBuddy calls `transfer_to_bolbuddy` to return seamlessly.
- **General English Stays with BolBuddy**: Everyday conversation, vocabulary questions (*"What does confident mean?"*), and casual practice remain with BolBuddy with **zero handoff triggers**.

---

### 3. Full Chat Context Preservation

When the specialist agent is instantiated, the existing conversation history is transferred seamlessly using:
```python
copied_ctx = self.chat_ctx.copy(exclude_instructions=True)
interview_agent = InterviewBuddy(chat_ctx=copied_ctx, voice="Samar")
```

**Why this matters:**
If a learner previously said:
> *"My name is Ramesh, and I have an interview next week for a software internship."*

InterviewBuddy immediately inherits:
- Target role: Software Internship
- Timeline: Next week
- Focus: Technical & behavioral preparation

The learner is **never** asked to repeat their goal or background.

---

### 4. Specialist-Specific Murf Falcon Voices (Single Voice Pipeline)

- **Architecture**: STT (Deepgram Nova-3), LLM, Silero VAD, and LiveKit `AgentSession` remain completely unified. No duplicate `AgentSession` or parallel pipeline is created.
- **Specialist Voice Configuration**:
  - **BolBuddy** $\rightarrow$ Murf Falcon voice **"Anisha"** (warm, conversational Indian English & Hindi companion)
  - **InterviewBuddy** $\rightarrow$ Murf Falcon voice **"Samar"** (professional, articulate Indian English & Hindi mock interview coach)
  - **Future Specialists** (e.g. Viva Coach) $\rightarrow$ Murf Falcon voice **"Pooja"** / **"Kabir"**
- **TTS Factory**:
  ```python
  def create_murf_tts(
      voice: str = "Anisha",
      style: str = "Conversation",
      min_sentence_len: int = 1,
      text_pacing: bool = True,
  ) -> murf.TTS:
      return murf.TTS(
          voice=voice,
          style=style,
          tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=min_sentence_len),
          text_pacing=text_pacing,
      )
  ```

---

### 5. Frontend Specialist Handoff Experience

The UI gives InterviewBuddy a distinct, professional identity while maintaining a cohesive BolBuddy product experience:

1. **Active Agent Header**:
   - **BolBuddy**: Title: `BolBuddy` · Subtitle: `English Speaking Companion` · Voice Badge: `● Murf Falcon · Anisha`
   - **InterviewBuddy**: Title: `InterviewBuddy [ ✨ Specialist ]` · Subtitle: `Interview Practice Specialist` · Voice Badge: `● Murf Falcon · Samar`
2. **Prominent Interaction Pill**:
   - Displays a dedicated live badge above the Voice Orb showing which specialist is actively interacting with the learner.
3. **Smooth Handoff Transition Banner**:
   - Shows `Connecting to InterviewBuddy... (BolBuddy → InterviewBuddy)` $\rightarrow$ `✓ Connected to InterviewBuddy (Voice: Samar)`.
4. **Specialist Intro Card**:
   - Compact, non-blocking informational card detailing interview practice focus areas (Common questions, answer structure, spoken clarity).
5. **Clean Message Sanitization**:
   - All internal tool JSON parameters and function tags (`transfer_to_interview_buddy`, XML tags) are completely stripped from both spoken audio and the visual transcript.

---

## 📁 Repository Structure

```
day_9/
├── backend/
│   ├── src/
│   │   ├── agent.py                      # Main entrypoint: Assistant & InterviewBuddy classes
│   │   ├── groq_key_manager.py           # Multi-key LLM rotation
│   │   ├── db.py                         # SQLite user persistence & analytics
│   │   └── prompts/
│   │       ├── system_prompt.py          # BolBuddy instructions & handoff rules
│   │       └── interview_prompt.py       # InterviewBuddy specialist system prompt
│   └── tests/
│       ├── test_handoff.py               # Day 9 LLM-as-judge & voice tests
│       └── ...                           # 72+ full regression tests
├── frontend/
│   ├── components/app/
│   │   ├── bolbuddy-session-view.tsx     # Session view with active agent branding
│   │   ├── handoff-transition-banner.tsx # Animated handoff transition pill
│   │   ├── specialist-intro-card.tsx     # InterviewBuddy practice intro card
│   │   ├── voice-orb.tsx                 # Real-time WebRTC audio visualizer
│   │   └── mic-button.tsx                # Microphone controls
│   ├── hooks/
│   │   └── useActiveAgent.ts             # Active agent detection & transition hook
│   └── utils.ts                          # Chat message sanitization & helpers
├── start_app.ps1                         # One-click Windows runner
├── start_app.sh                          # One-click macOS/Linux runner
└── README.md                             # This documentation
```

---

## 🚀 How to Run Day 9

### One-Click Launch (Recommended)

**Windows (PowerShell):**
```powershell
.\start_app.ps1
```

**macOS / Linux:**
```bash
./start_app.sh
```

---

### Manual Launch

**1. Start Backend:**
```bash
cd backend
uv sync
uv run python src/agent.py dev
```

**2. Start Frontend:**
```bash
cd frontend
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 🧪 Testing & Verification

### 1. Specialist Voice Configuration Test
```bash
cd backend
uv run pytest tests/test_handoff.py -k test_specialist_murf_voice_configuration -v
```

### 2. Full Backend Regression Suite (72 Tests)
```bash
cd backend
uv run pytest tests/test_analytics.py tests/test_async_memory.py tests/test_call_outcomes.py tests/test_escalation.py tests/test_groq_key_manager.py tests/test_layer2_state_machine.py tests/test_memory_db.py tests/test_memory_tools.py tests/test_phase10_failure_scenarios.py tests/test_phase2_schedule_model.py tests/test_phase3_scheduler.py tests/test_phase7_failure_handling.py tests/test_phase8_schedule_verification.py tests/test_retry_policy.py tests/test_telephony.py -v
```

### 3. Frontend Lint & Production Build
```bash
cd frontend
pnpm format:check
pnpm lint
pnpm build
```

---

## 🎬 Day 9 Video Demo Walkthrough

1. **Start Call**: Click **🎙 Talk to BolBuddy**.
   - BolBuddy greets with Indian voice **Anisha**.
   - Header shows: `BolBuddy` · `Murf Falcon · Anisha`.
2. **Request Interview Practice**: Say:
   > *"My name is Ramesh, and I have a software interview next week and want to practice."*
3. **Instant Handoff**:
   - BolBuddy immediately responds: *"Connecting you with InterviewBuddy now for focused interview practice."*
   - Banner slides in: `Connecting to InterviewBuddy... (BolBuddy → InterviewBuddy)`.
   - Header & Pill update to: `InterviewBuddy [ ✨ Specialist ]` · `Murf Falcon · Samar`.
   - Voice switches seamlessly to Indian male voice **Samar**.
4. **Mock Interview Question**:
   - InterviewBuddy asks: *"Hi Ramesh, let's start with a common question. Tell me about your software background."*
   - Full context (*Ramesh*, *software internship*, *next week*) is preserved without repeating!
