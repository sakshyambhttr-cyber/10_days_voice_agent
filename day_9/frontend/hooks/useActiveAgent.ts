"use client";

import { useEffect, useRef, useState } from "react";
import type { ReceivedMessage } from "@livekit/components-react";

export type ActiveAgentType = "bolbuddy" | "interview_buddy";
export type HandoffTransitionPhase = "idle" | "connecting" | "connected";

export interface ActiveAgentConfig {
  agentType: ActiveAgentType;
  name: string;
  role: string;
  statusLabel: string;
  badgeLabel: string;
  badgeIcon: string;
  voiceName: string;
  voiceProvider: string;
  voiceAccent: string;
  themeGradient: string;
  headerAccent: string;
  avatarText: string;
  avatarBg: string;
  listeningHint: string;
  speakingHint: string;
  tagline: string;
}

export const AGENT_CONFIGS: Record<ActiveAgentType, ActiveAgentConfig> = {
  bolbuddy: {
    agentType: "bolbuddy",
    name: "BolBuddy",
    role: "English Speaking Companion",
    statusLabel: "Practicing with BolBuddy",
    badgeLabel: "English Practice",
    badgeIcon: "🎙",
    voiceName: "Anisha",
    voiceProvider: "Murf Falcon",
    voiceAccent: "Indian Multilingual / English",
    themeGradient: "from-indigo-600 to-purple-700",
    headerAccent: "text-indigo-600",
    avatarText: "BB",
    avatarBg: "bg-gradient-to-br from-indigo-600 to-purple-700 text-white",
    listeningHint:
      "Speak naturally in English or Hinglish. BolBuddy is listening!",
    speakingHint: "Listen to BolBuddy. You can reply when finished.",
    tagline: "Voice-First English Practice Companion",
  },
  interview_buddy: {
    agentType: "interview_buddy",
    name: "InterviewBuddy",
    role: "Interview Practice Specialist",
    statusLabel: "InterviewBuddy is now helping you",
    badgeLabel: "🎯 Interview Practice",
    badgeIcon: "🎯",
    voiceName: "Samar",
    voiceProvider: "Murf Falcon",
    voiceAccent: "Indian Multilingual / English & Hindi",
    themeGradient: "from-blue-700 via-indigo-700 to-teal-700",
    headerAccent: "text-teal-600",
    avatarText: "IB",
    avatarBg: "bg-gradient-to-br from-blue-700 to-teal-700 text-white",
    listeningHint:
      "Speak clearly and structure your interview answer. InterviewBuddy is listening!",
    speakingHint: "Listen to InterviewBuddy’s interview question or feedback.",
    tagline: "Focused Mock Interview & Spoken Communication Specialist",
  },
};

export function useActiveAgent(
  messages: ReceivedMessage[],
  attributeAgent?: ActiveAgentType,
) {
  const [activeAgent, setActiveAgent] = useState<ActiveAgentType>("bolbuddy");
  const [targetAgent, setTargetAgent] =
    useState<ActiveAgentType>("interview_buddy");
  const [transitionPhase, setTransitionPhase] =
    useState<HandoffTransitionPhase>("idle");
  const [showSpecialistIntro, setShowSpecialistIntro] = useState(false);
  const prevAgentRef = useRef<ActiveAgentType>("bolbuddy");

  useEffect(() => {
    let detectedAgent: ActiveAgentType = "bolbuddy";
    let isHandoffSignal = false;

    // Direct WebRTC participant attribute has highest authority
    if (attributeAgent === "interview_buddy" || attributeAgent === "bolbuddy") {
      detectedAgent = attributeAgent;
      if (detectedAgent !== prevAgentRef.current) {
        isHandoffSignal = true;
      }
    } else {
      // Scan messages chronologically to detect agent state transitions
      for (const msg of messages) {
        const rawText =
          (msg as { message?: string }).message ||
          (msg as { text?: string }).text ||
          (msg as { transcript?: string }).transcript ||
          "";
        const text = String(rawText).toLowerCase();
        if (!text) continue;

        const isAgent = !msg.from?.isLocal;

        // 1. Check for transfer to InterviewBuddy or InterviewBuddy active speech
        if (
          text.includes("interviewbuddy") ||
          text.includes("transfer_to_interview_buddy") ||
          text.includes("connecting you now") ||
          text.includes("connecting you with interviewbuddy") ||
          text.includes("connecting you to interviewbuddy") ||
          text.includes("i'll connect you with interviewbuddy") ||
          text.includes("i'll connect you to interviewbuddy") ||
          text.includes("i'm interviewbuddy") ||
          (isAgent &&
            (text.includes("practice for your interview") ||
              text.includes("software interview") ||
              text.includes("mock interview") ||
              text.includes("interview questions") ||
              text.includes("what role are you preparing for")))
        ) {
          detectedAgent = "interview_buddy";
          isHandoffSignal = true;
        }

        // 2. Check for handback to BolBuddy
        if (
          text.includes("transfer_to_bolbuddy") ||
          text.includes("switching back now") ||
          text.includes("switching back") ||
          text.includes("connect you back with bolbuddy") ||
          text.includes("connecting you back with bolbuddy") ||
          text.includes("connecting you back to bolbuddy") ||
          text.includes("i'll connect you back with bolbuddy") ||
          text.includes("i'm bolbuddy") ||
          text.includes("welcome back to bolbuddy")
        ) {
          detectedAgent = "bolbuddy";
          isHandoffSignal = true;
        }
      }
    }

    // Handle agent transition triggers
    if (detectedAgent !== prevAgentRef.current) {
      const nextAgent = detectedAgent;
      prevAgentRef.current = nextAgent;
      setTargetAgent(nextAgent);
      setActiveAgent(nextAgent); // Update activeAgent immediately for instant header/voice sync

      if (isHandoffSignal || nextAgent === "interview_buddy") {
        setTransitionPhase("connecting");
        if (nextAgent === "interview_buddy") {
          setShowSpecialistIntro(true);
        }
        const timer1 = setTimeout(() => {
          setTransitionPhase("connected");
          const timer2 = setTimeout(() => {
            setTransitionPhase("idle");
          }, 500);
          return () => clearTimeout(timer2);
        }, 250);
        return () => clearTimeout(timer1);
      } else {
        setTransitionPhase("idle");
      }
    }
  }, [messages, attributeAgent]);

  const config = AGENT_CONFIGS[activeAgent];
  const targetConfig = AGENT_CONFIGS[targetAgent];

  return {
    activeAgent,
    config,
    targetConfig,
    transitionPhase,
    showSpecialistIntro,
    dismissSpecialistIntro: () => setShowSpecialistIntro(false),
  };
}
