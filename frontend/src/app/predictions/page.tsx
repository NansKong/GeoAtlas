"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  BrainCircuit,
  CheckCircle2,
  Filter,
  History,
  Target,
  TrendingUp,
  XCircle,
} from "lucide-react";

import { PredictionCard } from "@/components/PredictionCard";
import { fetchPredictionAccuracy, fetchPredictions, fetchPredictionSummary } from "@/lib/api";
import type { AccuracyMetrics, PredictionItem } from "@/lib/api";

const OUTCOME_FILTERS = [
  { value: "", label: "All Outcomes" },
  { value: "correct", label: "✅ Correct" },
  { value: "wrong", label: "❌ Wrong" },
  { value: "partial", label: "↔️ Partial" },
  { value: "pending", label: "⏳ Pending" },
];

const EVENT_TYPE_FILTERS = [
  { value: "", label: "All Types" },
  { value: "conflict", label: "Conflict" },
  { value: "sanction", label: "Sanctions" },
  { value: "trade_policy", label: "Trade Policy" },
  { value: "economic_data", label: "Economic Data" },
  { value: "energy_disruption", label: "Energy" },
  { value: "election", label: "Elections" },
  { value: "regulation", label: "Regulation" },
];

function AccuracyBar({ label, accuracy, total }: { label: string; accuracy: number; total: number }) {
  const pct = Math.round(accuracy * 100);
  const color =
    pct >= 70
      ? "bg-emerald-500"
      : pct >= 55
        ? "bg-amber-400"
        : "bg-rose-400";
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 truncate text-xs font-medium text-gray-600">{label.replace(/_/g, " ")}</span>
      <div className="relative h-3 flex-1 overflow-hidden rounded-full bg-gray-100">
        <div className={`absolute inset-y-0 left-0 rounded-full transition-all duration-700 ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-16 text-right text-xs font-bold text-gray-800">{pct}%</span>
      <span className="w-12 text-right text-[10px] text-gray-400">{total} pred</span>
    </div>
  );
}

function AccuracyPanel({ metrics }: { metrics: AccuracyMetrics }) {
  const overallPct = metrics.overall_accuracy !== undefined && metrics.overall_accuracy !== null
    ? Math.round(metrics.overall_accuracy * 100)
    : null;

  const eventEntries = Object.entries(metrics.by_event_type || {}).sort((a, b) => b[1].accuracy - a[1].accuracy);
  const modelEntries = Object.entries(metrics.by_model || {}).sort((a, b) => b[1].accuracy - a[1].accuracy);
  const horizonEntries = Object.entries(metrics.by_horizon || {}).sort((a, b) => b[1].accuracy - a[1].accuracy);

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {/* Overall ring */}
      <div className="flex flex-col items-center justify-center rounded-[24px] border border-gray-200 bg-white p-5 shadow-sm">
        <div className="relative flex h-28 w-28 items-center justify-center">
          <svg className="absolute inset-0 -rotate-90" viewBox="0 0 120 120" fill="none">
            <circle cx="60" cy="60" r="52" stroke="#e5e7eb" strokeWidth="10" />
            <circle
              cx="60" cy="60" r="52"
              stroke={overallPct !== null && overallPct >= 60 ? "#10b981" : "#ef4444"}
              strokeWidth="10"
              strokeDasharray={`${(overallPct ?? 0) * 3.267} 326.7`}
              strokeLinecap="round"
              className="transition-all duration-1000"
            />
          </svg>
          <span className="text-2xl font-bold text-gray-900">{overallPct !== null ? `${overallPct}%` : "-"}</span>
        </div>
        <p className="mt-3 text-sm font-semibold text-gray-700">Overall Accuracy</p>
        <p className="mt-1 text-xs text-gray-400">
          {metrics.total_correct} / {metrics.total_resolved} resolved
        </p>
      </div>

      {/* By Event Type */}
      <div className="rounded-[24px] border border-gray-200 bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center gap-2">
          <Target className="h-4 w-4 text-geo-600" />
          <h3 className="text-sm font-semibold text-gray-900">By Event Type</h3>
        </div>
        <div className="space-y-2">
          {eventEntries.length > 0
            ? eventEntries.map(([key, val]) => <AccuracyBar key={key} label={key} accuracy={val.accuracy} total={val.total} />)
            : <p className="text-xs text-gray-400">No resolved predictions yet</p>}
        </div>
      </div>

      {/* By Model + Horizon */}
      <div className="space-y-4">
        <div className="rounded-[24px] border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <BrainCircuit className="h-4 w-4 text-geo-600" />
            <h3 className="text-sm font-semibold text-gray-900">By Model</h3>
          </div>
          <div className="space-y-2">
            {modelEntries.length > 0
              ? modelEntries.map(([key, val]) => <AccuracyBar key={key} label={key} accuracy={val.accuracy} total={val.total} />)
              : <p className="text-xs text-gray-400">No model data</p>}
          </div>
        </div>
        <div className="rounded-[24px] border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-geo-600" />
            <h3 className="text-sm font-semibold text-gray-900">By Horizon</h3>
          </div>
          <div className="space-y-2">
            {horizonEntries.length > 0
              ? horizonEntries.map(([key, val]) => <AccuracyBar key={key} label={key} accuracy={val.accuracy} total={val.total} />)
              : <p className="text-xs text-gray-400">No horizon data</p>}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PredictionsPage() {
  const [mode, setMode] = useState<"live" | "history">("live");
  const [outcomeFilter, setOutcomeFilter] = useState("");
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  const { data: summary } = useQuery({
    queryKey: ["prediction-summary"],
    queryFn: fetchPredictionSummary,
    staleTime: 60_000,
  });

  const { data: accuracy } = useQuery({
    queryKey: ["prediction-accuracy"],
    queryFn: fetchPredictionAccuracy,
    staleTime: 60_000,
  });

  const { data: predictions, isLoading } = useQuery({
    queryKey: ["predictions", mode],
    queryFn: () =>
      fetchPredictions({
        history_only: mode === "history",
        published_only: mode === "live",
        limit: 80,
      }),
    staleTime: 30_000,
  });

  const filtered = useMemo(() => {
    let items = predictions ?? [];
    if (outcomeFilter) items = items.filter((p) => p.outcome === outcomeFilter);
    if (eventTypeFilter) items = items.filter((p) => p.event_type === eventTypeFilter);
    return items;
  }, [predictions, outcomeFilter, eventTypeFilter]);

  const outcomeStats = useMemo(() => {
    const items = predictions ?? [];
    return {
      correct: items.filter((p) => p.outcome === "correct").length,
      wrong: items.filter((p) => p.outcome === "wrong").length,
      partial: items.filter((p) => p.outcome === "partial").length,
      pending: items.filter((p) => p.outcome === "pending").length,
    };
  }, [predictions]);

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-6">
      {/* Header */}
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-geo-600" />
            <h1 className="text-xl font-bold text-gray-900">Prediction Engine</h1>
          </div>
          <p className="mt-2 max-w-3xl text-sm text-gray-500">
            Full closed-loop prediction lifecycle with transparent model accuracy and resolved outcome tracking.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-full border border-gray-200 bg-white p-1">
            <button
              onClick={() => setMode("live")}
              className={`rounded-full px-4 py-2 text-sm font-semibold ${mode === "live" ? "bg-gray-900 text-white" : "text-gray-600"}`}
            >
              Live Surface
            </button>
            <button
              onClick={() => setMode("history")}
              className={`rounded-full px-4 py-2 text-sm font-semibold ${mode === "history" ? "bg-gray-900 text-white" : "text-gray-600"}`}
            >
              History
            </button>
          </div>
          <button
            onClick={() => setShowFilters((v) => !v)}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-2 text-sm font-semibold transition-colors ${showFilters ? "border-geo-300 bg-geo-50 text-geo-700" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}
          >
            <Filter className="h-4 w-4" />
            Filters
          </button>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="mb-6 grid gap-3 md:grid-cols-5">
        <StatCard icon={<BarChart3 className="h-4 w-4 text-geo-700" />} label="Total" value={`${summary?.total_predictions ?? 0}`} />
        <StatCard icon={<History className="h-4 w-4 text-geo-700" />} label="Resolved" value={`${summary?.resolved_predictions ?? 0}`} />
        <StatCard icon={<CheckCircle2 className="h-4 w-4 text-emerald-600" />} label="Correct" value={`${outcomeStats.correct}`} accent="emerald" />
        <StatCard icon={<XCircle className="h-4 w-4 text-rose-600" />} label="Wrong" value={`${outcomeStats.wrong}`} accent="rose" />
        <StatCard
          icon={<BrainCircuit className="h-4 w-4 text-geo-700" />}
          label="Accuracy"
          value={summary?.overall_accuracy !== undefined && summary?.overall_accuracy !== null ? `${(summary.overall_accuracy * 100).toFixed(1)}%` : "-"}
          hint={summary?.feature_enabled === false ? "Auto-disabled < 50%" : "Shipping threshold 60%"}
        />
      </div>

      {/* Filters */}
      {showFilters && (
        <div className="mb-6 animate-fade-up rounded-[24px] border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.2em] text-gray-400">Outcome</label>
              <select
                value={outcomeFilter}
                onChange={(e) => setOutcomeFilter(e.target.value)}
                className="h-9 rounded-full border border-gray-300 bg-white px-3 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-geo-300"
              >
                {OUTCOME_FILTERS.map((f) => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.2em] text-gray-400">Event Type</label>
              <select
                value={eventTypeFilter}
                onChange={(e) => setEventTypeFilter(e.target.value)}
                className="h-9 rounded-full border border-gray-300 bg-white px-3 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-geo-300"
              >
                {EVENT_TYPE_FILTERS.map((f) => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
            </div>
            {(outcomeFilter || eventTypeFilter) && (
              <button
                onClick={() => { setOutcomeFilter(""); setEventTypeFilter(""); }}
                className="mt-4 text-xs font-semibold text-geo-600 hover:underline"
              >
                Clear all
              </button>
            )}
          </div>
        </div>
      )}

      {/* Accuracy Dashboard */}
      {mode === "history" && accuracy && (
        <section className="mb-8">
          <div className="mb-4 flex items-center gap-2">
            <Target className="h-5 w-5 text-geo-600" />
            <h2 className="text-base font-semibold text-gray-900">Accuracy Dashboard</h2>
            <span className="rounded-full bg-geo-50 px-2 py-0.5 text-xs font-medium text-geo-700">Closed-Loop</span>
          </div>
          <AccuracyPanel metrics={accuracy} />
        </section>
      )}

      {/* Predictions Grid */}
      {isLoading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="h-72 animate-pulse rounded-[26px] border border-gray-200 bg-gray-100" />
          ))}
        </div>
      ) : filtered.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {filtered.map((prediction) => (
            <PredictionCard key={prediction.id} prediction={prediction} />
          ))}
        </div>
      ) : (
        <div className="rounded-[28px] border border-dashed border-gray-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold text-gray-700">
            {outcomeFilter || eventTypeFilter ? "No predictions match this filter" : "No predictions available"}
          </p>
          <p className="mt-2 text-sm text-gray-500">
            {outcomeFilter || eventTypeFilter
              ? "Try adjusting your outcome or event type filters."
              : "Create predictions through the backend API, then this surface will show live-eligible predictions and resolved history."}
          </p>
        </div>
      )}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  hint,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  accent?: string;
}) {
  const accentBg = accent === "emerald" ? "bg-emerald-50" : accent === "rose" ? "bg-rose-50" : "bg-geo-50";
  return (
    <div className="rounded-[24px] border border-gray-200 bg-white px-4 py-4 shadow-sm">
      <div className={`mb-3 inline-flex rounded-full p-2 ${accentBg}`}>{icon}</div>
      <p className="text-sm font-semibold text-gray-900">{label}</p>
      <p className="mt-1 text-2xl font-bold text-gray-900">{value}</p>
      {hint ? <p className="mt-1 text-xs text-gray-500">{hint}</p> : null}
    </div>
  );
}
