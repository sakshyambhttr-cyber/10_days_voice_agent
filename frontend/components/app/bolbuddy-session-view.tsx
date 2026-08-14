'use client';

import React, { useEffect, useRef, useState } from 'react';
import {
  Brain,
  Briefcase,
  LifeBuoy,
  MessageSquare,
  Mic,
  MicOff,
  PhoneOff,
  Sparkles,
} from 'lucide-react';
import { motion } from 'motion/react';
import {
  useAgent,
  useLocalParticipant,
  useParticipantAttributes,
  useSessionContext,
  useSessionMessages,
  useVoiceAssistant,
} from '@livekit/components-react';
import { Button } from '@/components/ui/button';
import { ActiveAgentType, useActiveAgent } from '@/hooks/useActiveAgent';
import { cn } from '@/lib/shadcn/utils';
import { cleanChatMessage, getPersistentUserId } from '@/lib/utils';
import { EvaluationFeedback, FeedbackCard } from './feedback-card';
import { HandoffTransitionBanner } from './handoff-transition-banner';
import { MemoryPanel, UserMemoryData } from './memory-panel';
import { MicButton } from './mic-button';
import { SpecialistIntroCard } from './specialist-intro-card';
import { VoiceOrb, VoiceState } from './voice-orb';

export function BolBuddySessionView() {
  const session = useSessionContext();
  const { messages } = useSessionMessages(session);
  const { agent, state: agentState } = useAgent();
  const { attributes } = useParticipantAttributes({ participant: agent });
  const activeAgentFromAttr = (attributes?.active_agent as ActiveAgentType) || undefined;
  const { localParticipant } = useLocalParticipant();
  const { state: voiceState, audioTrack } = useVoiceAssistant();
  const isMuted = localParticipant ? !localParticipant.isMicrophoneEnabled : false;

  // Active agent detection and handoff state tracking
  const {
    activeAgent,
    config: agentConfig,
    targetConfig,
    transitionPhase,
    showSpecialistIntro,
    dismissSpecialistIntro,
  } = useActiveAgent(messages, activeAgentFromAttr);

  const isInterviewBuddy = activeAgent === 'interview_buddy';

  // Compute active normalized voice state
  const activeState: VoiceState = (voiceState ||
    agentState ||
    (session.isConnected ? 'listening' : 'idle')) as VoiceState;

  const [showTranscript, setShowTranscript] = useState(false);
  const [showMemoryDrawer, setShowMemoryDrawer] = useState(false);
  const [memory, setMemory] = useState<UserMemoryData | null>(null);
  const [isCallEnded, setIsCallEnded] = useState(false);
  const [extractedFeedback, setExtractedFeedback] = useState<EvaluationFeedback | null>(null);
  const [activeTicketRef, setActiveTicketRef] = useState<string | null>(null);

  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // Auto scroll transcript when visible
  useEffect(() => {
    if (showTranscript && scrollAreaRef.current) {
      scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight;
    }
  }, [messages, showTranscript]);

  // Parse active ticket reference ID (ESC-XXXX) from messages
  useEffect(() => {
    for (const msg of messages) {
      if (!msg.from?.isLocal && msg.message) {
        const refMatch = msg.message.match(/ESC-[A-Z0-9]+/i);
        if (refMatch) {
          setActiveTicketRef(refMatch[0].toUpperCase());
        }
      }
    }
  }, [messages]);

  // Extract structured feedback if score_spoken_answer was returned in chat history
  useEffect(() => {
    for (const msg of messages) {
      if (!msg.from?.isLocal && msg.message) {
        // 1. Try JSON match first
        try {
          const match = msg.message.match(/\{[\s\S]*"score"[\s\S]*\}/);
          if (match) {
            const parsed = JSON.parse(match[0]);
            if (typeof parsed.score === 'number') {
              setExtractedFeedback({
                score: parsed.score,
                strength: parsed.strength || 'Clear ideas',
                improvement: parsed.improvement || 'Natural phrasing',
                example: parsed.example || '',
              });
              continue;
            }
          }
        } catch {
          // Ignore JSON parse errors
        }

        // 2. Fallback to spoken text pattern match (e.g., "7 out of 10")
        const spokenScoreMatch = msg.message.match(/(\d+)\s*out of\s*10/i);
        if (spokenScoreMatch) {
          const scoreNum = parseInt(spokenScoreMatch[1], 10);
          const lowerMsg = msg.message.toLowerCase();

          let strength = 'Clear ideas';
          if (lowerMsg.includes('ideas were clear') || lowerMsg.includes('clear ideas')) {
            strength = 'Clear ideas';
          } else if (lowerMsg.includes('clear and easy')) {
            strength = 'Clear delivery';
          } else if (lowerMsg.includes('structure')) {
            strength = 'Good structure';
          }

          let improvement = 'Natural phrasing';
          if (lowerMsg.includes('phrasing') || lowerMsg.includes('natural')) {
            improvement = 'Natural phrasing';
          } else if (lowerMsg.includes('filler')) {
            improvement = 'Reduce filler words';
          } else if (lowerMsg.includes('vocabulary')) {
            improvement = 'Varied vocabulary';
          }

          setExtractedFeedback({
            score: scoreNum,
            strength: strength,
            improvement: improvement,
          });
        }
      }
    }
  }, [messages]);

  const getStatusText = () => {
    if (isCallEnded) return 'Conversation ended';
    switch (activeState) {
      case 'connecting':
        return `Connecting to ${agentConfig.name}...`;
      case 'listening':
        return isMuted ? 'Microphone Muted' : 'Listening to you';
      case 'thinking':
        return `${agentConfig.name} is thinking...`;
      case 'speaking':
        return `${agentConfig.name} is speaking`;
      default:
        return `${agentConfig.name} is ready`;
    }
  };

  const getStatusBadgeColor = () => {
    if (isInterviewBuddy) {
      switch (activeState) {
        case 'listening':
          return isMuted
            ? 'bg-rose-100 text-rose-700 border-rose-200'
            : 'bg-teal-100 text-teal-800 border-teal-200';
        case 'thinking':
          return 'bg-blue-100 text-blue-800 border-blue-200';
        case 'speaking':
          return 'bg-emerald-100 text-emerald-800 border-emerald-200';
        default:
          return 'bg-teal-50 text-teal-700 border-teal-200';
      }
    }
    switch (activeState) {
      case 'listening':
        return isMuted
          ? 'bg-rose-100 text-rose-700 border-rose-200'
          : 'bg-purple-100 text-purple-700 border-purple-200';
      case 'thinking':
        return 'bg-indigo-100 text-indigo-700 border-indigo-200';
      case 'speaking':
        return 'bg-emerald-100 text-emerald-700 border-emerald-200';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
  };

  // Toggle microphone
  const toggleMicrophone = async () => {
    if (localParticipant) {
      await localParticipant.setMicrophoneEnabled(isMuted);
    }
  };

  // End conversation & show post-call feedback view
  const handleEndCall = () => {
    setIsCallEnded(true);
    try {
      const userId = getPersistentUserId();
      if (userId) {
        fetch('/api/analytics/finalize', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ userId }),
        }).catch(() => {});
      }
    } catch {
      // Ignore finalize fetch error
    }
    session.end();
  };

  // Restart session
  const handleTryAgain = () => {
    setIsCallEnded(false);
    setExtractedFeedback(null);
    session.start();
  };

  // Return to home
  const handleBackHome = () => {
    session.end();
  };

  // Render Post-Call Feedback Card View
  if (isCallEnded) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#F8FAFC] p-6 text-slate-900">
        <FeedbackCard
          feedback={extractedFeedback}
          onTryAgain={handleTryAgain}
          onBackHome={handleBackHome}
        />
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-between overflow-hidden bg-[#FAFAF8] text-slate-900 selection:bg-indigo-100">
      {/* Top Bar Header */}
      <header
        className={cn(
          'z-30 flex shrink-0 items-center justify-between border-b px-6 py-3.5 backdrop-blur-md transition-colors duration-300',
          isInterviewBuddy
            ? 'border-teal-200/70 bg-gradient-to-r from-teal-50/90 via-white/80 to-blue-50/90'
            : 'border-slate-200/60 bg-white/80'
        )}
      >
        <div className="flex items-center gap-3">
          <div
            className={cn(
              'flex size-9 items-center justify-center rounded-xl text-white shadow-sm transition-all duration-300',
              agentConfig.avatarBg
            )}
          >
            {isInterviewBuddy ? (
              <Briefcase className="size-4.5" />
            ) : (
              <Mic className="size-4 animate-pulse" />
            )}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-extrabold tracking-tight text-slate-900">
                {agentConfig.name}
              </h1>
              {isInterviewBuddy && (
                <span className="inline-flex items-center gap-1 rounded-full bg-teal-100 px-2 py-0.5 text-[10px] font-extrabold text-teal-800">
                  <Sparkles className="size-2.5 text-teal-600" />
                  Specialist
                </span>
              )}
            </div>
            <p className="text-[11px] font-medium text-slate-500">{agentConfig.role}</p>
          </div>
        </div>

        <div className="flex items-center gap-2.5 sm:gap-3">
          {/* Active Voice Indicator Pill */}
          <div
            className={cn(
              'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-all',
              isInterviewBuddy
                ? 'border-teal-300/80 bg-teal-50 text-teal-800'
                : 'border-indigo-200/80 bg-indigo-50/60 text-indigo-800'
            )}
          >
            <span className="size-1.5 rounded-full bg-emerald-500" />
            <span>
              {agentConfig.voiceProvider} ·{' '}
              <strong className="text-slate-900">{agentConfig.voiceName}</strong>
            </span>
          </div>

          {/* Voice State Badge */}
          <span
            className={cn(
              'flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold transition-all',
              getStatusBadgeColor()
            )}
          >
            <span className="size-2 animate-ping rounded-full bg-current" />
            <span>{getStatusText()}</span>
          </span>

          {/* Specialist Badge */}
          {isInterviewBuddy && (
            <span className="hidden items-center gap-1 rounded-full border border-teal-300 bg-teal-100 px-2.5 py-1 text-xs font-bold text-teal-900 sm:flex">
              <span>🎯 Interview Practice</span>
            </span>
          )}

          {/* Transcript Toggle */}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowTranscript(!showTranscript)}
            className={cn(
              'text-xs font-semibold transition-all',
              showTranscript
                ? 'bg-indigo-100/70 text-indigo-900 hover:bg-indigo-200/70'
                : 'text-slate-600 hover:text-slate-900'
            )}
          >
            <MessageSquare className="mr-1.5 size-4" />
            {showTranscript ? 'Hide' : 'Transcript'}
          </Button>

          {/* Memory Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowMemoryDrawer(true)}
            className="border-indigo-200 bg-indigo-50/50 text-xs font-semibold text-indigo-700 hover:bg-indigo-100/70 hover:text-indigo-900"
          >
            <Brain className="mr-1.5 size-4 text-indigo-600" />
            Memory
          </Button>
        </div>
      </header>

      {/* Main Voice Interaction Area */}
      <main className="relative mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col items-center justify-between overflow-y-auto px-4 py-3 sm:px-6">
        {/* Handoff Transition Shimmer Banner */}
        <HandoffTransitionBanner
          phase={transitionPhase}
          fromAgentName={agentConfig.name}
          targetAgentName={targetConfig.name}
          voiceName={targetConfig.voiceName}
        />

        {/* Specialist Intro Card (Dismissible / Auto-fading) */}
        {isInterviewBuddy && showSpecialistIntro && (
          <SpecialistIntroCard onDismiss={dismissSpecialistIntro} />
        )}

        {/* Active Support Ticket Banner Card */}
        {activeTicketRef && (
          <motion.div
            initial={{ opacity: 0, y: -15 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-3 flex w-full max-w-md shrink-0 items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50/90 px-4 py-2.5 shadow-sm backdrop-blur-md"
          >
            <div className="flex items-center gap-3">
              <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-amber-500/20 text-amber-700">
                <LifeBuoy className="size-4" />
              </div>
              <div className="text-left">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-slate-900">Support Request Created</span>
                  <span className="rounded bg-amber-200/80 px-1.5 py-0.5 text-[10px] font-extrabold text-amber-900">
                    {activeTicketRef}
                  </span>
                </div>
                <p className="text-[11px] font-medium text-slate-600">
                  A human teacher will review it. You can continue practicing!
                </p>
              </div>
            </div>
          </motion.div>
        )}

        {/* Animated Voice Orb Visual Center */}
        <div className="my-auto flex flex-col items-center justify-center space-y-4 py-2 text-center">
          {/* Prominent Active Agent Interaction Pill */}
          <motion.div
            key={agentConfig.name}
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            className={cn(
              'inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-xs font-bold shadow-sm transition-all duration-300',
              isInterviewBuddy
                ? 'border-teal-300/80 bg-teal-50/95 text-teal-900 shadow-teal-900/5'
                : 'border-indigo-200/80 bg-indigo-50/95 text-indigo-900 shadow-indigo-900/5'
            )}
          >
            <span
              className={cn(
                'size-2 rounded-full',
                isInterviewBuddy ? 'animate-pulse bg-teal-500' : 'animate-pulse bg-indigo-500'
              )}
            />
            <span>
              {isInterviewBuddy
                ? '🎯 InterviewBuddy Active · Mock Interview Specialist'
                : '🎙 BolBuddy Active · English Speaking Companion'}
            </span>
            <span className="text-[10px] font-medium text-slate-500">
              · Voice: {agentConfig.voiceName}
            </span>
          </motion.div>

          <VoiceOrb
            state={activeState}
            isMuted={isMuted}
            audioTrack={audioTrack}
            onClick={toggleMicrophone}
          />

          {/* Accessible Live Guidance Text */}
          <div aria-live="polite" className="space-y-1">
            <h2 className="text-base font-extrabold tracking-tight text-slate-900 sm:text-lg">
              {getStatusText()}
            </h2>
            <p className="max-w-md text-xs font-medium text-slate-500 sm:text-sm">
              {isMuted
                ? 'Microphone muted. Tap the mic button or orb to resume.'
                : activeState === 'speaking'
                  ? agentConfig.speakingHint
                  : activeState === 'thinking'
                    ? `${agentConfig.name} is processing your answer...`
                    : agentConfig.listeningHint}
            </p>
            {/* Mobile Voice Badge */}
            <p className="pt-0.5 text-[11px] font-medium text-slate-400 md:hidden">
              Voice: {agentConfig.voiceProvider} · {agentConfig.voiceName}
            </p>
          </div>

          {/* State-Aware Microphone Control Button */}
          <div className="pt-1">
            <MicButton
              state={activeState}
              isMuted={isMuted}
              agentName={agentConfig.name}
              onStart={session.start}
              onToggleMute={toggleMicrophone}
            />
          </div>
        </div>

        {/* Live Transcript Stream (Preserves Full Conversation Across Handoff) */}
        {showTranscript && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="my-3 flex h-44 w-full max-w-2xl shrink-0 flex-col rounded-2xl border border-slate-200/80 bg-white/95 p-3.5 shadow-lg backdrop-blur-md md:h-52"
          >
            <div className="mb-2 flex items-center justify-between border-b border-slate-100 pb-2">
              <span className="flex items-center gap-1.5 text-xs font-bold text-slate-700">
                <MessageSquare className="size-3.5 text-indigo-600" />
                Live Conversation Transcript
              </span>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-medium text-slate-400">
                  {isInterviewBuddy ? '🎯 Interview Specialist Mode' : 'General English Mode'}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowTranscript(false)}
                  className="h-6 text-[10px] text-slate-400 hover:text-slate-700"
                >
                  Hide
                </Button>
              </div>
            </div>

            <div
              ref={scrollAreaRef}
              className="scrollbar-thin scrollbar-thumb-slate-200 flex-1 space-y-2.5 overflow-y-auto pr-2"
            >
              {messages.length === 0 ? (
                <div className="flex h-full items-center justify-center text-xs text-slate-400">
                  No messages yet. Speak to begin your conversation!
                </div>
              ) : (
                messages.map((msg, idx) => {
                  const isUser = msg.from?.isLocal;
                  const rawText =
                    msg.message ||
                    (msg as { text?: string }).text ||
                    (msg as { transcript?: string }).transcript ||
                    '';
                  const cleanedText = cleanChatMessage(rawText);
                  if (!cleanedText) return null;

                  // Determine if this specific message was from InterviewBuddy
                  const lowerText = cleanedText.toLowerCase();
                  const isInterviewBuddyMsg =
                    !isUser &&
                    (lowerText.includes('interviewbuddy') ||
                      lowerText.includes('interview practice') ||
                      (isInterviewBuddy && idx >= messages.length - 3));

                  return (
                    <div
                      key={msg.id || idx}
                      className={cn(
                        'flex max-w-[85%] items-start gap-2.5 text-xs leading-relaxed',
                        isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'
                      )}
                    >
                      <div
                        className={cn(
                          'flex size-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold shadow-xs',
                          isUser
                            ? 'bg-slate-200 text-slate-700'
                            : isInterviewBuddyMsg
                              ? 'bg-gradient-to-br from-blue-700 to-teal-700 text-white'
                              : 'bg-gradient-to-br from-indigo-600 to-purple-700 text-white'
                        )}
                      >
                        {isUser ? 'You' : isInterviewBuddyMsg ? 'IB' : 'BB'}
                      </div>
                      <div
                        className={cn(
                          'rounded-2xl border p-2.5 shadow-xs',
                          isUser
                            ? 'rounded-tr-xs border-indigo-600 bg-indigo-600 text-white'
                            : isInterviewBuddyMsg
                              ? 'rounded-tl-xs border-teal-200/80 bg-teal-50/80 text-slate-900'
                              : 'rounded-tl-xs border-slate-200/60 bg-slate-100 text-slate-900'
                        )}
                      >
                        {cleanedText}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </motion.div>
        )}
      </main>

      {/* Memory Control Drawer */}
      <MemoryPanel
        isOpen={showMemoryDrawer}
        memory={memory}
        onClose={() => setShowMemoryDrawer(false)}
        onMemoryCleared={() => setMemory(null)}
      />

      {/* Bottom Control Bar - Sticky & Pinned */}
      <footer className="sticky bottom-0 z-30 flex shrink-0 items-center justify-center gap-4 border-t border-slate-200/80 bg-white/95 p-3.5 shadow-lg backdrop-blur-md">
        <Button
          size="lg"
          variant={isMuted ? 'destructive' : 'outline'}
          onClick={toggleMicrophone}
          className="size-12 cursor-pointer rounded-full shadow-sm transition-transform active:scale-95"
          title={isMuted ? 'Unmute microphone' : 'Mute microphone'}
        >
          {isMuted ? <MicOff className="size-5" /> : <Mic className="size-5 text-indigo-600" />}
        </Button>

        <Button
          size="lg"
          variant="destructive"
          onClick={handleEndCall}
          className="flex cursor-pointer items-center gap-2 rounded-full bg-rose-600 px-6 text-xs font-bold text-white shadow-md transition-transform hover:bg-rose-700 active:scale-95"
          title="Disconnect from session"
        >
          <PhoneOff className="size-4" />
          <span>End Conversation</span>
        </Button>
      </footer>
    </div>
  );
}
