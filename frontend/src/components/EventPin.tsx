"use client";
import { motion } from "framer-motion";
import { MapPin, Plus } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

interface AffectedAsset {
  ticker: string;
  name?: string;
  impact_direction: string;
  impact_strength?: number;
  confidence_score?: number;
}

export interface EventPinData {
  id: string;
  title: string;
  event_type: string;
  country?: string;
  severity?: number;
  confidence_score?: number;
  published_at?: string;
  impact_count?: number;
  description?: string;
  tags?: string[];
  affected_assets?: AffectedAsset[];
}

const EVENT_TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  conflict: { bg: "#fee2e2", text: "#991b1b" },
  sanction: { bg: "#fef3c7", text: "#92400e" },
  trade_policy: { bg: "#dbeafe", text: "#1e40af" },
  economic_data: { bg: "#d1fae5", text: "#065f46" },
  energy_disruption: { bg: "#fde8d8", text: "#9a3412" },
  election: { bg: "#ede9fe", text: "#5b21b6" },
  regulation: { bg: "#f0fdf4", text: "#166534" },
};

const SEVERITY_COLORS = ["", "#10b981", "#84cc16", "#f59e0b", "#f97316", "#ef4444"];

interface EventPinProps {
  event: EventPinData;
  onSave?: (event: EventPinData) => void;
}

export function EventPin({ event, onSave }: EventPinProps) {
  const typeStyle = EVENT_TYPE_COLORS[event.event_type] ?? { bg: "#f3f4f6", text: "#374151" };
  const typeLabel = event.event_type.replace(/_/g, " ");
  const timeAgo = event.published_at
    ? formatDistanceToNow(new Date(event.published_at), { addSuffix: true })
    : null;
  const affectedAssets = event.affected_assets ?? [];
  const tags = event.tags ?? [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="pin-card group relative"
    >
      {event.severity && (
        <div
          className="h-1 w-full"
          style={{ backgroundColor: SEVERITY_COLORS[event.severity] ?? "#e5e7eb" }}
        />
      )}

      <div className="p-4 pb-3">
        <span
          className="mb-2 inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold"
          style={{ background: typeStyle.bg, color: typeStyle.text }}
        >
          {typeLabel.toUpperCase()}
        </span>

        <h3 className="mb-2 line-clamp-3 text-[14px] font-semibold leading-snug text-gray-900">
          {event.title}
        </h3>

        <div className="mb-3 flex items-center gap-2 text-xs text-gray-400">
          {event.country && (
            <span className="flex items-center gap-1">
              <MapPin className="h-3 w-3" />
              {event.country}
            </span>
          )}
          {timeAgo && <span>- {timeAgo}</span>}
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {event.impact_count !== undefined && event.impact_count > 0 && (
              <span className="text-xs text-gray-500">
                {event.impact_count} asset{event.impact_count !== 1 ? "s" : ""} affected
              </span>
            )}
            {event.confidence_score !== undefined && (
              <span className="text-xs font-medium text-gray-400">
                {Math.round(event.confidence_score * 100)}% confidence
              </span>
            )}
          </div>
        </div>

        {tags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {tags.slice(0, 4).map((tag) => (
              <span
                key={`${event.id}-${tag}`}
                className="inline-flex items-center rounded-full border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-600"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        {affectedAssets.length > 0 && (
          <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50 p-2.5">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
              Affected Assets
            </p>
            <div className="flex flex-wrap gap-1.5">
              {affectedAssets.slice(0, 5).map((asset) => {
                const dir = asset.impact_direction.toLowerCase();
                const tone =
                  dir === "positive"
                    ? "bg-emerald-100 text-emerald-800 border-emerald-200"
                    : dir === "negative"
                    ? "bg-rose-100 text-rose-800 border-rose-200"
                    : "bg-slate-100 text-slate-700 border-slate-200";
                return (
                  <span
                    key={`${event.id}-${asset.ticker}`}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-semibold ${tone}`}
                    title={asset.name || asset.ticker}
                  >
                    <span>{asset.ticker}</span>
                  </span>
                );
              })}
              {affectedAssets.length > 5 && (
                <span className="inline-flex items-center rounded-full border border-gray-200 bg-white px-2 py-1 text-[11px] font-semibold text-gray-500">
                  +{affectedAssets.length - 5}
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="pointer-events-none absolute inset-0 rounded-[var(--pin-radius)] opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100">
        <button
          onClick={(event_) => {
            event_.stopPropagation();
            onSave?.(event);
          }}
          className="pointer-events-auto absolute right-3 top-3 flex items-center gap-1 rounded-full bg-geo-500 px-3 py-1.5 text-xs font-bold text-white shadow-md transition-all hover:bg-geo-600 active:scale-95"
        >
          <Plus className="h-3 w-3" />
          Save
        </button>
      </div>
    </motion.div>
  );
}
