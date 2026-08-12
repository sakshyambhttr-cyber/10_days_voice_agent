# Day 8 — BolBuddy Call Analytics Dashboard & Voice Interaction UI

Welcome to **Day 8** of the **Murf 10 Days of Voice Agents** challenge for **BolBuddy** — your voice-first spoken English learning companion.

This module introduces a real-time **Call Analytics Dashboard** backed by actual LiveKit call records stored in SQLite, alongside a state-aware **Voice Orb** and **Microphone Control System** built on LiveKit session states.

---

## 🌟 Key Highlights & Features

### 1. Real Call Analytics Engine (`backend/src/db.py`)
- **Persistent SQLite Tracking**: Stores real call metadata in the `call_analytics` table (`call_id`, `user_id`, `started_at`, `ended_at`, `duration`, `channel`, `outcome`, `failure_reason`, `completed_activities`).
- **No Hardcoded Data**: Dashboard metrics are calculated dynamically using real backend database queries (`get_analytics_summary()`, `get_recent_calls()`).
- **Smart Outcome Classification**:
  - **Successful Calls**: Session duration $\ge$ 30s, exercise tools invoked (`fetch_next_exercise`), answer scoring completed (`score_spoken_answer`), memory saved (`save_user_memory`), or session ended gracefully.
  - **Failed Calls**: Immediate early hangups (< 30s with zero interaction) or unhandled system errors.

### 2. State-Aware Voice Orb (`frontend/components/app/voice-orb.tsx`)
- **Visual Centerpiece**: A large, approachable Voice Orb designed specifically for spoken English practice.
- **Real LiveKit State Binding**: Binds directly to LiveKit's `useVoiceAssistant()` hook without timers:
  - **IDLE**: Calm orb with gentle breathing animation.
  - **CONNECTING**: Pulsing orb with loading spinner indicator.
  - **LISTENING**: Expanding purple/indigo wave aura indicating user can speak now.
  - **THINKING**: Slower rotating dashed ring indicating AI processing.
  - **SPEAKING**: Dynamic emerald voice aura powered by `AgentAudioVisualizerAura` and real audio track volume.
  - **DISCONNECTED**: Smooth reset to idle state.
- **Accessibility**: Includes `prefers-reduced-motion` support.

### 3. Redesigned Microphone Button (`frontend/components/app/mic-button.tsx`)
- **State-Aware UI**: Prevents double-clicks and invalid interactions during `CONNECTING`, `THINKING`, and `SPEAKING` states.
- **Explicit Labels**: Contextual status text (*"🎙 Start Speaking"*, *"Connecting..."*, *"Microphone Active (Listening...)"*, *"Thinking... Please wait"*, *"BolBuddy is Speaking"*).
- **Accessibility**: ARIA labels (`aria-label`, `aria-pressed`, `aria-live`), focus outlines (`focus-visible:ring-2`).

### 4. Interactive Analytics Drawer (`frontend/components/app/analytics-dashboard.tsx`)
- **Live Metrics Cards**:
  - **Total Calls**: Total completed/recorded calls.
  - **Successful Calls**: Successful practice sessions.
  - **Failed Calls**: Early hangups or dropped calls.
  - **Success Rate %**: Calculated success percentage.
  - **Completed Activities**: Total learning exercises & evaluations completed.
- **Recent Calls Table**: Displays timestamp, duration, channel (Browser/SIP), outcome badge, and failure reason breakdown.
- **Live Refresh Button**: Instantly re-queries metrics from backend API routes (`/api/analytics/calls`, `/api/analytics/recent`, `/api/analytics/finalize`).

---

## 📁 Directory Structure

```
day_8/
├── README.md                           # Day 8 documentation & guide
├── backend/
│   ├── src/
│   │   ├── db.py                       # SQLite schema & call_analytics functions
│   │   └── agent.py                    # Voice agent entrypoint & session lifecycle
│   └── tests/
│       └── test_analytics.py           # Unit tests for call analytics & outcome logic
└── frontend/
    ├── app/
    │   └── api/
    │       └── analytics/
    │           ├── calls/route.ts      # GET API endpoint for summary metrics
    │           ├── recent/route.ts     # GET API endpoint for recent calls
    │           └── finalize/route.ts   # POST API endpoint for instant call finalization
    └── components/
        └── app/
            ├── analytics-dashboard.tsx # Analytics drawer UI component
            ├── voice-orb.tsx           # Voice Orb component (LiveKit state-bound)
            ├── mic-button.tsx          # State-aware Microphone button
            └── bolbuddy-session-view.tsx # Main conversation screen
```

---

## 🚀 Running & Testing Day 8

### Backend Unit Tests
To run the LLM & analytics test suite:
```bash
cd backend
uv sync
uv run pytest tests/test_analytics.py
```

### Running All Services via Startup Scripts
You can start all services (LiveKit server, backend agent, outbound telephony agent, and frontend UI) using the included startup scripts:

- **Windows (PowerShell)**:
  ```powershell
  .\start_app.ps1
  ```
- **macOS / Linux (Bash)**:
  ```bash
  chmod +x start_app.sh
  ./start_app.sh
  ```

### Manual Individual Commands
1. **Start Backend Agent**:
   ```bash
   cd backend
   uv run python src/agent.py dev
   ```

2. **Start Frontend App**:
   ```bash
   cd frontend
   pnpm install
   pnpm dev
   ```

3. **Open Browser & Practice**:
   - Navigate to `http://localhost:3000`.
   - Click **"Analytics"** in the top header to view the Live Analytics Dashboard.
   - Start a practice call, interact with BolBuddy, and watch the analytics update live upon finishing!

---

## 🔒 Code Quality & Standards

- **Backend**: Verified with `ruff check src/ tests/` and `pytest`.
- **Frontend**: Verified with `prettier --check` and Next.js ESLint `pnpm lint`.
