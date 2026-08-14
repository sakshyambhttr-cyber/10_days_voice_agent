"use client";

import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Award,
  BarChart3,
  CheckCircle2,
  Clock,
  PhoneCall,
  RefreshCw,
  TrendingUp,
  X,
  XCircle,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { getPersistentUserId } from "@/lib/utils";

export interface AnalyticsSummary {
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  success_rate: number;
  completed_activities: number;
  failure_reasons: Record<string, number>;
}

export interface RecentCallRecord {
  call_id: string;
  user_id?: string;
  started_at: string;
  ended_at?: string;
  duration: number;
  duration_formatted: string;
  channel: "Browser" | "SIP";
  outcome: "Successful" | "Failed";
  failure_reason?: string;
  completed_activities: number;
}

interface AnalyticsDashboardProps {
  isOpen: boolean;
  onClose: () => void;
}

export function AnalyticsDashboard({
  isOpen,
  onClose,
}: AnalyticsDashboardProps) {
  const [summary, setSummary] = useState<AnalyticsSummary>({
    total_calls: 0,
    successful_calls: 0,
    failed_calls: 0,
    success_rate: 0,
    completed_activities: 0,
    failure_reasons: {},
  });
  const [recentCalls, setRecentCalls] = useState<RecentCallRecord[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchAnalytics = async () => {
    try {
      setLoading(true);
      const userId = getPersistentUserId();
      if (userId) {
        await fetch("/api/analytics/finalize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ userId }),
        }).catch(() => {});
      }

      const [sumRes, recRes] = await Promise.all([
        fetch("/api/analytics/calls"),
        fetch("/api/analytics/recent?limit=10"),
      ]);

      const sumData = await sumRes.json();
      const recData = await recRes.json();

      if (sumData.success) {
        setSummary({
          total_calls: sumData.total_calls || 0,
          successful_calls: sumData.successful_calls || 0,
          failed_calls: sumData.failed_calls || 0,
          success_rate: sumData.success_rate || 0,
          completed_activities: sumData.completed_activities || 0,
          failure_reasons: sumData.failure_reasons || {},
        });
      }

      if (recData.success && Array.isArray(recData.recent_calls)) {
        setRecentCalls(recData.recent_calls);
      }
    } catch (err) {
      console.warn("Failed to fetch analytics dashboard data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchAnalytics();
    }
  }, [isOpen]);

  const formatReasonName = (reason: string) => {
    switch (reason.toLowerCase()) {
      case "user_hangup":
        return "User Ended Early";
      case "incomplete_exercise":
        return "Incomplete Exercise";
      case "user_declined":
        return "User Declined Call";
      case "technical_error":
        return "Technical Failure";
      case "no_response":
        return "No Response";
      default:
        return reason.replace(/_/g, " ");
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/60 backdrop-blur-xs">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0"
          />

          {/* Drawer Content */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 220 }}
            className="relative flex h-full w-full max-w-2xl flex-col border-l border-slate-800 bg-slate-900 text-slate-100 shadow-2xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/90 p-6">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-md shadow-indigo-500/20">
                  <BarChart3 className="size-5 text-white" />
                </div>
                <div>
                  <h2 className="text-xl font-bold tracking-tight text-white">
                    BolBuddy Analytics
                  </h2>
                  <p className="text-xs font-medium text-slate-400">
                    See how learners are using BolBuddy and completing practice
                    sessions.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={fetchAnalytics}
                  disabled={loading}
                  className="rounded-full border-slate-700 bg-slate-800 text-xs font-semibold text-slate-300 hover:bg-slate-700 hover:text-white"
                >
                  <RefreshCw
                    className={`mr-1.5 size-3.5 ${loading ? "animate-spin text-indigo-400" : ""}`}
                  />
                  <span>Refresh Analytics</span>
                </Button>

                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onClose}
                  className="rounded-full text-slate-400 hover:bg-slate-800 hover:text-white"
                >
                  <X className="size-5" />
                </Button>
              </div>
            </div>

            {/* Main Scrollable Body */}
            <div className="flex-1 space-y-6 overflow-y-auto p-6 text-sm">
              {/* Primary Top Metric Cards */}
              <div className="grid grid-cols-3 gap-3 sm:gap-4">
                {/* Total Calls */}
                <div className="flex flex-col rounded-2xl border border-slate-800 bg-slate-800/60 p-4 transition-all hover:border-slate-700">
                  <div className="flex items-center justify-between text-slate-400">
                    <span className="text-[11px] font-bold tracking-wider text-slate-400 uppercase">
                      Total Calls
                    </span>
                    <PhoneCall className="size-4 text-indigo-400" />
                  </div>
                  <span className="mt-3 text-3xl font-black text-white">
                    {summary.total_calls}
                  </span>
                  <span className="mt-1 text-[11px] text-slate-400">
                    Actual calls logged
                  </span>
                </div>

                {/* Successful Calls */}
                <div className="flex flex-col rounded-2xl border border-emerald-500/30 bg-emerald-950/20 p-4 transition-all hover:border-emerald-500/40">
                  <div className="flex items-center justify-between text-emerald-400">
                    <span className="text-[11px] font-bold tracking-wider text-emerald-400 uppercase">
                      Successful
                    </span>
                    <CheckCircle2 className="size-4 text-emerald-400" />
                  </div>
                  <span className="mt-3 text-3xl font-black text-emerald-400">
                    {summary.successful_calls}
                  </span>
                  <span className="mt-1 text-[11px] text-emerald-400/80">
                    Completed interaction
                  </span>
                </div>

                {/* Failed Calls */}
                <div className="flex flex-col rounded-2xl border border-amber-500/30 bg-amber-950/20 p-4 transition-all hover:border-amber-500/40">
                  <div className="flex items-center justify-between text-amber-400">
                    <span className="text-[11px] font-bold tracking-wider text-amber-400 uppercase">
                      Failed
                    </span>
                    <XCircle className="size-4 text-amber-400" />
                  </div>
                  <span className="mt-3 text-3xl font-black text-amber-400">
                    {summary.failed_calls}
                  </span>
                  <span className="mt-1 text-[11px] text-amber-400/80">
                    Left early or error
                  </span>
                </div>
              </div>

              {/* Secondary Metrics Row */}
              <div className="grid grid-cols-2 gap-3 sm:gap-4">
                {/* Success Rate */}
                <div className="flex items-center gap-4 rounded-2xl border border-indigo-500/20 bg-gradient-to-r from-indigo-950/40 via-purple-950/20 to-slate-800/40 p-4">
                  <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-indigo-500/20 text-indigo-400">
                    <TrendingUp className="size-5" />
                  </div>
                  <div>
                    <span className="text-xs font-bold text-slate-400">
                      Success Rate
                    </span>
                    <div className="text-2xl font-extrabold text-white">
                      {summary.success_rate}%
                    </div>
                  </div>
                </div>

                {/* Completed Activities */}
                <div className="flex items-center gap-4 rounded-2xl border border-purple-500/20 bg-gradient-to-r from-purple-950/40 via-indigo-950/20 to-slate-800/40 p-4">
                  <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-purple-500/20 text-purple-400">
                    <Award className="size-5" />
                  </div>
                  <div>
                    <span className="text-xs font-bold text-slate-400">
                      Completed Activities
                    </span>
                    <div className="text-2xl font-extrabold text-white">
                      {summary.completed_activities}
                    </div>
                  </div>
                </div>
              </div>

              {/* Failure Reasons Breakdown (if failed calls exist) */}
              {Object.keys(summary.failure_reasons).length > 0 && (
                <div className="rounded-2xl border border-slate-800 bg-slate-800/40 p-4">
                  <div className="mb-3 flex items-center gap-2 font-bold text-slate-300">
                    <AlertTriangle className="size-4 text-amber-400" />
                    <span>Failure Reasons Breakdown</span>
                  </div>
                  <div className="space-y-2">
                    {Object.entries(summary.failure_reasons).map(
                      ([reason, count]) => (
                        <div
                          key={reason}
                          className="flex items-center justify-between rounded-xl bg-slate-900/60 px-3 py-2 text-xs"
                        >
                          <span className="text-slate-300">
                            {formatReasonName(reason)}
                          </span>
                          <span className="rounded-full bg-amber-500/20 px-2.5 py-0.5 font-bold text-amber-300">
                            {count}
                          </span>
                        </div>
                      ),
                    )}
                  </div>
                </div>
              )}

              {/* Recent Calls Table */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-slate-200">
                    Recent Call History
                  </h3>
                  <span className="text-xs font-medium text-slate-400">
                    Latest {recentCalls.length} calls
                  </span>
                </div>

                {recentCalls.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-slate-800 p-8 text-center text-slate-500">
                    <Activity className="mx-auto mb-2 size-8 text-slate-600" />
                    <p className="font-semibold text-slate-400">
                      No calls recorded yet
                    </p>
                    <p className="text-xs">
                      Start a voice session to generate real call analytics
                      data.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2.5">
                    {recentCalls.map((call) => (
                      <div
                        key={call.call_id}
                        className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-800/50 p-3.5 transition-colors hover:bg-slate-800/80"
                      >
                        <div className="flex items-center gap-3">
                          <div
                            className={`flex size-9 items-center justify-center rounded-xl ${
                              call.outcome === "Successful"
                                ? "bg-emerald-500/20 text-emerald-400"
                                : "bg-amber-500/20 text-amber-400"
                            }`}
                          >
                            {call.outcome === "Successful" ? (
                              <CheckCircle2 className="size-4" />
                            ) : (
                              <XCircle className="size-4" />
                            )}
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-white">
                                {new Date(call.started_at).toLocaleTimeString(
                                  [],
                                  {
                                    hour: "2-digit",
                                    minute: "2-digit",
                                  },
                                )}
                              </span>
                              <span className="rounded-md bg-slate-700/60 px-1.5 py-0.5 text-[10px] font-bold text-slate-300 uppercase">
                                {call.channel}
                              </span>
                            </div>
                            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-400">
                              <Clock className="size-3" />
                              <span>{call.duration_formatted}</span>
                              {call.failure_reason && (
                                <span className="text-amber-400/90">
                                  • {formatReasonName(call.failure_reason)}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>

                        <div className="text-right">
                          <span
                            className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ${
                              call.outcome === "Successful"
                                ? "border border-emerald-500/30 bg-emerald-500/20 text-emerald-400"
                                : "border border-amber-500/30 bg-amber-500/20 text-amber-400"
                            }`}
                          >
                            {call.outcome}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
