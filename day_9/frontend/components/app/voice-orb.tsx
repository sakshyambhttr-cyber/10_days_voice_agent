"use client";

import React from "react";
import type { LocalAudioTrack, RemoteAudioTrack } from "livekit-client";
import { Loader2, Mic, MicOff, Volume2 } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import type {
  AgentState,
  TrackReferenceOrPlaceholder,
} from "@livekit/components-react";
import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";
import { cn } from "@/lib/shadcn/utils";

export type VoiceState =
  | "idle"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "disconnected";

interface VoiceOrbProps {
  state: VoiceState | AgentState;
  isMuted?: boolean;
  audioTrack?: TrackReferenceOrPlaceholder | LocalAudioTrack | RemoteAudioTrack;
  onClick?: () => void;
  className?: string;
}

export function VoiceOrb({
  state = "idle",
  isMuted = false,
  audioTrack,
  onClick,
  className,
}: VoiceOrbProps) {
  const shouldReduceMotion = useReducedMotion();

  const normalizedState: VoiceState =
    (state === "initializing" ? "connecting" : (state as VoiceState)) || "idle";

  // Get status color tokens
  const getGlowColor = () => {
    switch (normalizedState) {
      case "connecting":
        return "from-amber-400/30 via-indigo-500/30 to-purple-600/30";
      case "listening":
        return isMuted
          ? "from-rose-500/20 via-slate-500/20 to-indigo-500/20"
          : "from-purple-500/40 via-indigo-500/40 to-blue-500/30";
      case "thinking":
        return "from-indigo-500/40 via-purple-600/40 to-slate-700/30";
      case "speaking":
        return "from-emerald-400/40 via-teal-500/40 to-indigo-600/30";
      case "disconnected":
      case "idle":
      default:
        return "from-indigo-400/20 via-purple-500/20 to-slate-400/10";
    }
  };

  const getOrbGradient = () => {
    switch (normalizedState) {
      case "connecting":
        return "from-amber-500 via-indigo-600 to-purple-700";
      case "listening":
        return isMuted
          ? "from-slate-700 via-slate-800 to-rose-950"
          : "from-indigo-600 via-purple-600 to-indigo-800";
      case "thinking":
        return "from-purple-700 via-indigo-800 to-slate-900";
      case "speaking":
        return "from-emerald-600 via-teal-600 to-indigo-800";
      case "disconnected":
      case "idle":
      default:
        return "from-indigo-600 via-purple-600 to-indigo-900";
    }
  };

  const getBorderRing = () => {
    switch (normalizedState) {
      case "connecting":
        return "border-amber-400/50 shadow-amber-500/20";
      case "listening":
        return isMuted
          ? "border-rose-400/40 shadow-rose-500/20"
          : "border-purple-400/50 shadow-purple-500/30";
      case "thinking":
        return "border-indigo-400/60 shadow-indigo-500/30";
      case "speaking":
        return "border-emerald-400/60 shadow-emerald-500/30";
      case "disconnected":
      case "idle":
      default:
        return "border-indigo-300/30 shadow-indigo-500/10";
    }
  };

  // State animation variants
  const getScaleAnimation = () => {
    if (shouldReduceMotion) return { scale: 1 };
    switch (normalizedState) {
      case "connecting":
        return { scale: [1, 1.04, 1] };
      case "listening":
        return isMuted ? { scale: 1 } : { scale: [1, 1.06, 1] };
      case "thinking":
        return { scale: [1, 1.02, 1] };
      case "speaking":
        return { scale: [1, 1.08, 1] };
      default:
        return { scale: [1, 1.02, 1] };
    }
  };

  const getTransitionDuration = () => {
    switch (normalizedState) {
      case "connecting":
        return 2.0;
      case "listening":
        return 1.8;
      case "thinking":
        return 2.5;
      case "speaking":
        return 1.2;
      default:
        return 3.0;
    }
  };

  return (
    <div
      className={cn(
        "relative flex items-center justify-center selection:bg-none",
        className,
      )}
    >
      {/* Outer Ambient Glow Ring */}
      <motion.div
        animate={getScaleAnimation()}
        transition={{
          duration: getTransitionDuration(),
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className={cn(
          "absolute rounded-full bg-gradient-to-tr opacity-60 blur-2xl transition-all duration-700",
          "size-60 sm:size-72 md:size-80",
          getGlowColor(),
        )}
      />

      {/* Outer Pulsing Wave Ring for Speaking/Listening */}
      {(normalizedState === "listening" || normalizedState === "speaking") &&
        !shouldReduceMotion && (
          <motion.div
            initial={{ scale: 0.9, opacity: 0.7 }}
            animate={{ scale: [1, 1.25, 1.35], opacity: [0.6, 0.2, 0] }}
            transition={{
              duration: normalizedState === "speaking" ? 1.5 : 2.2,
              repeat: Infinity,
              ease: "easeOut",
            }}
            className={cn(
              "absolute rounded-full border border-current opacity-30",
              "size-48 sm:size-56 md:size-64",
              normalizedState === "speaking"
                ? "text-emerald-400"
                : "text-purple-400",
            )}
          />
        )}

      {/* Rotating Ring for Thinking State */}
      {normalizedState === "thinking" && !shouldReduceMotion && (
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
          className="absolute size-52 rounded-full border-2 border-dashed border-indigo-400/50 sm:size-60 md:size-68"
        />
      )}

      {/* Shader Aura Visualizer (when agent is speaking and audioTrack exists) */}
      {normalizedState === "speaking" && audioTrack && (
        <div className="absolute inset-0 z-10 flex items-center justify-center opacity-90">
          <AgentAudioVisualizerAura
            state={state}
            audioTrack={audioTrack}
            color="#10B981"
            className="size-48 sm:size-56 md:size-64"
          />
        </div>
      )}

      {/* Core Orb Container */}
      <motion.button
        type="button"
        onClick={onClick}
        disabled={normalizedState === "connecting"}
        aria-label={`BolBuddy Voice Orb: ${normalizedState}`}
        animate={getScaleAnimation()}
        transition={{
          duration: getTransitionDuration(),
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className={cn(
          "relative z-20 flex cursor-pointer items-center justify-center rounded-full bg-gradient-to-tr shadow-2xl transition-all duration-500 focus-visible:ring-4 focus-visible:ring-indigo-400 focus-visible:outline-hidden disabled:cursor-not-allowed",
          "size-44 sm:size-52 md:size-60",
          getOrbGradient(),
          getBorderRing(),
        )}
      >
        {/* Inner Glass Highlights */}
        <div className="absolute inset-2 rounded-full border border-white/25 bg-white/10 backdrop-blur-xs" />
        <div className="absolute inset-x-4 top-3 h-1/3 rounded-t-full bg-gradient-to-b from-white/20 to-transparent" />

        {/* Center Icon & Indicator */}
        <div className="relative z-30 flex flex-col items-center justify-center gap-2 text-white">
          {normalizedState === "connecting" && (
            <Loader2 className="size-10 animate-spin text-amber-200" />
          )}

          {normalizedState === "listening" &&
            (isMuted ? (
              <MicOff className="size-10 text-rose-300" />
            ) : (
              <Mic className="size-10 animate-pulse text-white" />
            ))}

          {normalizedState === "thinking" && (
            <Loader2 className="size-10 animate-spin text-indigo-200" />
          )}

          {normalizedState === "speaking" && (
            <Volume2 className="size-10 animate-pulse text-emerald-200" />
          )}

          {(normalizedState === "idle" ||
            normalizedState === "disconnected") && (
            <Mic className="size-10 text-white/90" />
          )}
        </div>
      </motion.button>
    </div>
  );
}
