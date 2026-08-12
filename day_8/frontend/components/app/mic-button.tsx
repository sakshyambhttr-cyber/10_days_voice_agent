'use client';

import React from 'react';
import { Loader2, Mic, MicOff, Volume2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/shadcn/utils';
import type { VoiceState } from './voice-orb';

interface MicButtonProps {
  state: VoiceState;
  isMuted?: boolean;
  onStart?: () => void;
  onToggleMute?: () => void;
  className?: string;
}

export function MicButton({
  state = 'idle',
  isMuted = false,
  onStart,
  onToggleMute,
  className,
}: MicButtonProps) {
  // 1. IDLE / DISCONNECTED: Start Speaking
  if (state === 'idle' || state === 'disconnected') {
    return (
      <Button
        onClick={onStart}
        size="lg"
        aria-label="Start English Practice Call"
        className={cn(
          'flex cursor-pointer items-center justify-center gap-2.5 rounded-full bg-indigo-600 px-8 py-6 text-sm font-extrabold text-white shadow-lg shadow-indigo-600/25 transition-all hover:scale-105 hover:bg-indigo-700 focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2',
          className
        )}
      >
        <Mic className="size-5 text-white" />
        <span>🎙 Start Speaking</span>
      </Button>
    );
  }

  // 2. CONNECTING: Disabled Loading Spinner
  if (state === 'connecting') {
    return (
      <Button
        disabled
        size="lg"
        aria-label="Connecting to BolBuddy"
        className={cn(
          'flex cursor-not-allowed items-center justify-center gap-2.5 rounded-full border border-amber-300 bg-amber-50 px-8 py-6 text-sm font-bold text-amber-800 opacity-90 shadow-sm',
          className
        )}
      >
        <Loader2 className="size-5 animate-spin text-amber-600" />
        <span>Connecting to BolBuddy...</span>
      </Button>
    );
  }

  // 3. THINKING: Disabled Processing State
  if (state === 'thinking') {
    return (
      <Button
        disabled
        size="lg"
        aria-label="BolBuddy is thinking and processing response"
        className={cn(
          'flex cursor-not-allowed items-center justify-center gap-2.5 rounded-full border border-indigo-200 bg-indigo-50/80 px-8 py-6 text-sm font-bold text-indigo-700 opacity-90 shadow-sm',
          className
        )}
      >
        <Loader2 className="size-5 animate-spin text-indigo-600" />
        <span>Thinking... Please wait</span>
      </Button>
    );
  }

  // 4. SPEAKING: Disabled Agent Speaking State
  if (state === 'speaking') {
    return (
      <Button
        disabled
        size="lg"
        aria-label="BolBuddy is speaking"
        className={cn(
          'flex cursor-not-allowed items-center justify-center gap-2.5 rounded-full border border-emerald-200 bg-emerald-50/90 px-8 py-6 text-sm font-bold text-emerald-800 opacity-90 shadow-sm',
          className
        )}
      >
        <Volume2 className="size-5 animate-pulse text-emerald-600" />
        <span>BolBuddy is Speaking</span>
      </Button>
    );
  }

  // 5. LISTENING: Interactive Microphone Button (Active Speak / Mute Toggle)
  return (
    <Button
      onClick={onToggleMute}
      size="lg"
      aria-label={isMuted ? 'Unmute Microphone' : 'Mute Microphone'}
      aria-pressed={!isMuted}
      className={cn(
        'flex cursor-pointer items-center justify-center gap-2.5 rounded-full px-8 py-6 text-sm font-extrabold shadow-md transition-all focus-visible:ring-2 focus-visible:ring-offset-2',
        isMuted
          ? 'border border-rose-300 bg-rose-50 text-rose-700 hover:bg-rose-100 focus-visible:ring-rose-400'
          : 'bg-purple-600 text-white shadow-purple-600/25 hover:bg-purple-700 focus-visible:ring-purple-400',
        className
      )}
    >
      {isMuted ? (
        <>
          <MicOff className="size-5 text-rose-600" />
          <span>Microphone Muted (Tap to Unmute)</span>
        </>
      ) : (
        <>
          <Mic className="size-5 animate-pulse text-white" />
          <span>Microphone Active (Listening...)</span>
        </>
      )}
    </Button>
  );
}
