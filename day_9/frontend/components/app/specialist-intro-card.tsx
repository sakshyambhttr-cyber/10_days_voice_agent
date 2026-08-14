"use client";

import React, { useEffect } from "react";
import { Briefcase, CheckCircle2, Sparkles, X } from "lucide-react";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";

interface SpecialistIntroCardProps {
  onDismiss: () => void;
}

export function SpecialistIntroCard({ onDismiss }: SpecialistIntroCardProps) {
  // Auto-dismiss after 7 seconds so the UI stays uncluttered and focused on conversation
  useEffect(() => {
    const timer = setTimeout(() => {
      onDismiss();
    }, 7000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <motion.div
      initial={{ opacity: 0, y: -10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -10, scale: 0.98 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="mb-3 w-full max-w-md shrink-0 overflow-hidden rounded-2xl border border-teal-200/90 bg-white/95 p-3.5 shadow-lg shadow-teal-900/5 backdrop-blur-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-700 to-teal-600 text-white shadow-sm">
            <Briefcase className="size-4" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h3 className="text-xs font-bold text-slate-900">
                InterviewBuddy Active
              </h3>
              <span className="inline-flex items-center gap-1 rounded-full bg-teal-100 px-1.5 py-0.5 text-[9px] font-extrabold text-teal-800">
                <Sparkles className="size-2 text-teal-600" />
                Specialist
              </span>
            </div>
            <p className="text-[10px] font-medium text-slate-500">
              Mock Interview & Spoken Practice
            </p>
          </div>
        </div>

        <button
          onClick={onDismiss}
          className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          aria-label="Dismiss specialist intro"
        >
          <X className="size-3.5" />
        </button>
      </div>

      <div className="mt-2 rounded-lg border border-teal-100 bg-teal-50/50 p-2 text-[11px] text-slate-700">
        <ul className="space-y-0.5 text-[10px] text-slate-600">
          <li className="flex items-center gap-1.5">
            <CheckCircle2 className="size-2.5 shrink-0 text-teal-600" />
            <span>Behavioral & role-specific mock questions</span>
          </li>
          <li className="flex items-center gap-1.5">
            <CheckCircle2 className="size-2.5 shrink-0 text-teal-600" />
            <span>Structured framing & immediate spoken feedback</span>
          </li>
        </ul>
      </div>

      <div className="mt-2 flex items-center justify-between pt-0.5">
        <span className="text-[10px] font-medium text-slate-400">
          Voice:{" "}
          <span className="font-semibold text-slate-600">
            Murf Falcon · Samar
          </span>
        </span>
        <Button
          size="sm"
          onClick={onDismiss}
          className="h-6 rounded-full bg-teal-700 px-2.5 text-[10px] font-bold text-white shadow-xs hover:bg-teal-800"
        >
          Start Practice
        </Button>
      </div>
    </motion.div>
  );
}
