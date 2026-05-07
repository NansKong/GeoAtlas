"use client";

import { formatDistanceToNow } from "date-fns";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Gauge,
  ShieldCheck,
  XCircle,
  MinusCircle,
  Timer,
} from "lucide-react";

import type { PredictionItem } from "@/lib/api";

function formatPct(value?: number | null, digits = 1) {
  if (value === undefined || value === null) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function formatAccuracy(value?: number | null) {
  if (value === undefined || value === null) return "No resolved history";
  return `${(value * 100).toFixed(1)}% accuracy`;
}

function directionTone(direction: string) {
  if (direction === "up") {
    return {
      chip: "border-emerald-200 bg-emerald-50 text-emerald-800",
      icon: <ArrowUpRight className="h-4 w-4" />,
      label: "Upside",
    };
  }
  if (direction === "down") {
    return {
      chip: "border-rose-200 bg-rose-50 text-rose-800",
      icon: <ArrowDownRight className="h-4 w-4" />,
      label: "Downside",
    };
  }
  return {
    chip: "border-slate-200 bg-slate-100 text-slate-700",
    icon: <ArrowRight className="h-4 w-4" />,
    label: "Flat",
  };
}

function outcomeBadge(outcome: string) {
  switch (outcome) {
    case "correct":
      return {
        cls: "bg-emerald-100 text-emerald-800 border-emerald-200",
        icon: <CheckCircle2 className="h-3.5 w-3.5" />,
        label: "Correct",
      };
    case "wrong":
      return {
        cls: "bg-rose-100 text-rose-800 border-rose-200",
        icon: <XCircle className="h-3.5 w-3.5" />,
        label: "Wrong",
      };
    case "partial":
      return {
        cls: "bg-amber-100 text-amber-800 border-amber-200",
        icon: <MinusCircle className="h-3.5 w-3.5" />,
        label: "Partial",
      };
    default:
      return {
        cls: "bg-slate-100 text-slate-600 border-slate-200",
        icon: <Timer className="h-3.5 w-3.5" />,
        label: "Pending",
      };
  }
}

function ComparisonBar({ predicted, actual }: { predicted?: number | null; actual?: number | null }) {
  if (predicted === undefined || predicted === null || actual === undefined || actual === null) return null;
  const maxAbs = Math.max(Math.abs(predicted), Math.abs(actual), 0.01);
  const scale = (v: number) => Math.min(Math.abs(v) / (maxAbs * 1.2), 1) * 100;

  return (
    <div className="mt-4 space-y-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-400">Predicted vs Actual</p>
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="w-16 text-right text-[11px] font-medium text-gray-500">Predicted</span>
          <div className="relative h-5 flex-1 overflow-hidden rounded-full bg-gray-100">
            <div
              className={`absolute inset-y-0 left-0 rounded-full transition-all ${predicted >= 0 ? "bg-emerald-400" : "bg-rose-400"}`}
              style={{ width: `${scale(predicted)}%` }}
            />
          </div>
          <span className="w-14 text-right text-xs font-bold text-gray-700">{formatPct(predicted)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-16 text-right text-[11px] font-medium text-gray-500">Actual</span>
          <div className="relative h-5 flex-1 overflow-hidden rounded-full bg-gray-100">
            <div
              className={`absolute inset-y-0 left-0 rounded-full transition-all ${actual >= 0 ? "bg-emerald-500" : "bg-rose-500"}`}
              style={{ width: `${scale(actual)}%` }}
            />
          </div>
          <span className="w-14 text-right text-xs font-bold text-gray-700">{formatPct(actual)}</span>
        </div>
      </div>
    </div>
  );
}

function TimelineProgress({ predictedAt, resolveAt, resolvedAt }: { predictedAt: string; resolveAt?: string | null; resolvedAt?: string | null }) {
  const start = new Date(predictedAt).getTime();
  const end = resolveAt ? new Date(resolveAt).getTime() : start + 24 * 60 * 60 * 1000;
  const now = resolvedAt ? new Date(resolvedAt).getTime() : Date.now();
  const progress = Math.min(Math.max((now - start) / (end - start), 0), 1) * 100;
  const isResolved = !!resolvedAt;

  return (
    <div className="mt-3">
      <div className="flex items-center justify-between text-[10px] font-medium text-gray-400">
        <span className="flex items-center gap-1"><Clock className="h-3 w-3" /> Predicted</span>
        <span>{isResolved ? "Resolved" : "Resolves"}</span>
      </div>
      <div className="relative mt-1 h-1.5 overflow-hidden rounded-full bg-gray-100">
        <div
          className={`absolute inset-y-0 left-0 rounded-full transition-all duration-700 ${isResolved ? "bg-geo-500" : "bg-geo-300"}`}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

export function PredictionCard({ prediction }: { prediction: PredictionItem }) {
  const tone = directionTone(prediction.predicted_direction);
  const outcome = outcomeBadge(prediction.outcome);
  const predictedAgo = formatDistanceToNow(new Date(prediction.predicted_at), { addSuffix: true });
  const resolvedAgo = prediction.resolved_at
    ? formatDistanceToNow(new Date(prediction.resolved_at), { addSuffix: true })
    : null;

  return (
    <article className="rounded-[26px] border border-gray-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">
            {prediction.event_type.replace(/_/g, " ")}
          </p>
          <h3 className="mt-1 text-base font-semibold text-gray-900">{prediction.event_title}</h3>
          <p className="mt-1 text-sm text-gray-500">
            {prediction.ticker}
            {prediction.asset_name ? ` · ${prediction.asset_name}` : ""}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${tone.chip}`}>
            {tone.icon}
            {tone.label}
          </span>
          <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-bold ${outcome.cls}`}>
            {outcome.icon}
            {outcome.label}
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Metric label="Range" value={formatPct(prediction.predicted_change_pct)} />
        <Metric
          label="Confidence"
          value={
            prediction.confidence_score !== undefined && prediction.confidence_score !== null
              ? `${Math.round(prediction.confidence_score * 100)}%`
              : "-"
          }
        />
        <Metric label="Horizon" value={prediction.prediction_horizon} />
      </div>

      {prediction.outcome !== "pending" && (
        <ComparisonBar predicted={prediction.predicted_change_pct} actual={prediction.actual_change_pct} />
      )}

      <TimelineProgress
        predictedAt={prediction.predicted_at}
        resolveAt={prediction.resolve_at}
        resolvedAt={prediction.resolved_at}
      />

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
          <Gauge className="h-3.5 w-3.5" />
          {formatAccuracy(prediction.model_accuracy)}
        </span>
        <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
          <ShieldCheck className="h-3.5 w-3.5" />
          {prediction.event_type_accuracy !== null && prediction.event_type_accuracy !== undefined
            ? `${(prediction.event_type_accuracy * 100).toFixed(1)}% event-type accuracy`
            : "Event type not yet back-tested"}
        </span>
      </div>

      <div className="mt-4 rounded-2xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm text-gray-600">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-200/60 px-2 py-0.5 text-xs font-semibold text-gray-700">
            {prediction.model_version}
          </span>
          <span className="text-xs">Predicted {predictedAgo}</span>
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <span>
            Actual move:{" "}
            <span className="font-semibold text-gray-900">
              {formatPct(prediction.actual_change_pct)}
            </span>
          </span>
        </div>
        {resolvedAgo ? <p className="mt-2 text-xs text-gray-500">Resolved {resolvedAgo}</p> : null}
      </div>

      {!prediction.feature_enabled ? (
        <p className="mt-3 text-xs font-medium text-rose-700">
          Prediction surface auto-disabled because resolved accuracy fell below the production threshold.
        </p>
      ) : null}
      {prediction.feature_enabled && !prediction.eligible_for_display ? (
        <p className="mt-3 text-xs font-medium text-amber-700">
          Hidden from public prediction shipping until this event type clears the 60% back-test threshold.
        </p>
      ) : null}
    </article>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white px-3 py-2">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-400">{label}</p>
      <p className="mt-1 text-sm font-semibold text-gray-900">{value}</p>
    </div>
  );
}
