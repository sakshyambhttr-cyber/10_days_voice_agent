'use client';

import React from 'react';
import { Briefcase, CheckCircle2, Sparkles, X } from 'lucide-react';
import { motion } from 'motion/react';
import { Button } from '@/components/ui/button';

interface SpecialistIntroCardProps {
  onDismiss: () => void;
}

export function SpecialistIntroCard({ onDismiss }: SpecialistIntroCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -12, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -12, scale: 0.97 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="mb-4 w-full max-w-lg overflow-hidden rounded-2xl border border-teal-200/80 bg-white/95 p-4 shadow-xl shadow-teal-900/5 backdrop-blur-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-700 to-teal-600 text-white shadow-sm">
            <Briefcase className="size-4.5" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h3 className="text-sm font-bold text-slate-900">InterviewBuddy</h3>
              <span className="inline-flex items-center gap-1 rounded-full bg-teal-100 px-2 py-0.5 text-[10px] font-bold text-teal-800">
                <Sparkles className="size-2.5 text-teal-600" />
                Specialist
              </span>
            </div>
            <p className="text-[11px] font-medium text-slate-500">
              Job Interview & Mock Interview Practice
            </p>
          </div>
        </div>

        <button
          onClick={onDismiss}
          className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          aria-label="Dismiss specialist intro"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="mt-3 rounded-xl border border-teal-100 bg-teal-50/50 p-2.5 text-xs text-slate-700">
        <p className="mb-1.5 font-semibold text-teal-900">I will help you practice:</p>
        <ul className="space-y-1 text-[11px] text-slate-600">
          <li className="flex items-center gap-1.5">
            <CheckCircle2 className="size-3 shrink-0 text-teal-600" />
            <span>Common behavioral and role-specific interview questions</span>
          </li>
          <li className="flex items-center gap-1.5">
            <CheckCircle2 className="size-3 shrink-0 text-teal-600" />
            <span>Structured answer framing & self-introductions</span>
          </li>
          <li className="flex items-center gap-1.5">
            <CheckCircle2 className="size-3 shrink-0 text-teal-600" />
            <span>Spoken clarity, answer confidence, and concise feedback</span>
          </li>
        </ul>
      </div>

      <div className="mt-3 flex items-center justify-between pt-1">
        <span className="text-[11px] font-medium text-slate-400">
          Voice: <span className="font-semibold text-slate-600">Murf Falcon · Samar</span>
        </span>
        <Button
          size="sm"
          onClick={onDismiss}
          className="h-7 rounded-full bg-teal-700 px-3 text-xs font-bold text-white shadow-sm hover:bg-teal-800"
        >
          Start Practice
        </Button>
      </div>
    </motion.div>
  );
}
