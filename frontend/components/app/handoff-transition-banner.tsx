'use client';

import React from 'react';
import { ArrowRight, CheckCircle, Loader2, Sparkles } from 'lucide-react';
import { motion } from 'motion/react';
import type { HandoffTransitionPhase } from '@/hooks/useActiveAgent';

interface HandoffTransitionBannerProps {
  phase: HandoffTransitionPhase;
  fromAgentName?: string;
  targetAgentName?: string;
  voiceName?: string;
}

export function HandoffTransitionBanner({
  phase,
  fromAgentName = 'BolBuddy',
  targetAgentName = 'InterviewBuddy',
  voiceName = 'Samar',
}: HandoffTransitionBannerProps) {
  if (phase === 'idle') return null;

  const isConnecting = phase === 'connecting';

  return (
    <motion.div
      initial={{ opacity: 0, y: -16, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -16, scale: 0.95 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="mb-4 flex w-full max-w-md items-center justify-between gap-3 rounded-2xl border border-teal-300/80 bg-gradient-to-r from-teal-50 via-indigo-50 to-blue-50 px-4 py-3 shadow-lg shadow-teal-900/10 backdrop-blur-md"
    >
      <div className="flex items-center gap-3">
        <div
          className={`flex size-8 shrink-0 items-center justify-center rounded-xl ${
            isConnecting ? 'bg-teal-600 text-white' : 'bg-emerald-600 text-white'
          }`}
        >
          {isConnecting ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <CheckCircle className="size-4" />
          )}
        </div>

        <div className="text-left">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-slate-900">
              {isConnecting
                ? `Connecting to ${targetAgentName}...`
                : `Connected to ${targetAgentName}`}
            </span>
            <span className="py-0.2 inline-flex items-center gap-0.5 rounded-full bg-teal-200/80 px-1.5 text-[9px] font-extrabold text-teal-900">
              <Sparkles className="size-2 text-teal-700" />
              Specialist
            </span>
          </div>

          <p className="text-[11px] font-medium text-slate-600">
            {isConnecting ? (
              <span className="flex items-center gap-1">
                <span>{fromAgentName}</span>
                <ArrowRight className="size-2.5 text-slate-400" />
                <span className="font-semibold text-teal-800">{targetAgentName}</span>
              </span>
            ) : (
              <span>
                Murf Falcon · <span className="font-bold text-teal-800">{voiceName}</span> (Indian
                Voice) active
              </span>
            )}
          </p>
        </div>
      </div>
    </motion.div>
  );
}
