"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Plus, Trash2 } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

import {
  createWatchlist,
  deleteWatchlist,
  fetchWatchlist,
  type WatchlistItem,
} from "@/lib/api";

function getErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Request failed.";
}

export function WatchlistPanel() {
  const queryClient = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [isAuthed, setIsAuthed] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setIsAuthed(Boolean(localStorage.getItem("access_token")));
    }
  }, []);

  const watchlistQuery = useQuery({
    queryKey: ["watchlist"],
    queryFn: fetchWatchlist,
    enabled: isAuthed,
  });

  const createMutation = useMutation({
    mutationFn: createWatchlist,
    onSuccess: async () => {
      setTicker("");
      await queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteWatchlist,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });

  const items = useMemo(() => watchlistQuery.data ?? [], [watchlistQuery.data]);

  return (
    <section className="mt-8 rounded-[28px] border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <Activity className="h-5 w-5 text-geo-600" />
        <h2 className="text-base font-bold text-gray-900">Watchlist</h2>
      </div>
      <p className="mt-2 max-w-3xl text-sm text-gray-500">
        Track assets and keep the latest linked event impact visible in one place.
      </p>

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <input
          value={ticker}
          onChange={(event) => setTicker(event.target.value.toUpperCase())}
          placeholder="Add by ticker, for example NVDA"
          className="h-10 flex-1 rounded-full border border-gray-300 bg-white px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
        />
        <button
          onClick={() => {
            if (!ticker.trim()) return;
            createMutation.mutate({ ticker: ticker.trim() });
          }}
          disabled={!isAuthed || !ticker.trim() || createMutation.isPending}
          className="inline-flex h-10 items-center justify-center gap-1 rounded-full bg-gray-900 px-4 text-sm font-semibold text-white disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Add Asset
        </button>
      </div>

      {!isAuthed ? (
        <p className="mt-3 text-sm text-amber-700">Login required to manage a personal watchlist.</p>
      ) : null}
      {createMutation.isError ? (
        <p className="mt-3 text-sm text-red-700">{getErrorMessage(createMutation.error)}</p>
      ) : null}

      <div className="mt-4 space-y-3">
        {watchlistQuery.isLoading ? (
          Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="h-24 animate-pulse rounded-2xl border border-gray-200 bg-gray-100" />
          ))
        ) : items.length > 0 ? (
          items.map((item) => <WatchlistRow key={item.id} item={item} onDelete={deleteMutation.mutate} />)
        ) : (
          <div className="rounded-2xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-sm text-gray-500">
            No tracked assets yet.
          </div>
        )}
      </div>
    </section>
  );
}

function WatchlistRow({
  item,
  onDelete,
}: {
  item: WatchlistItem;
  onDelete: (id: string) => void;
}) {
  const latestImpact = item.latest_impact;
  const directionTone =
    latestImpact?.impact_direction === "positive"
      ? "bg-emerald-100 text-emerald-800"
      : latestImpact?.impact_direction === "negative"
      ? "bg-rose-100 text-rose-800"
      : "bg-slate-100 text-slate-700";

  return (
    <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-gray-900 px-2.5 py-1 text-xs font-bold text-white">
              {item.asset.ticker}
            </span>
            <p className="text-sm font-semibold text-gray-900">{item.asset.name}</p>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            {item.asset.asset_type}
            {item.asset.sector ? ` - ${item.asset.sector}` : ""}
            {item.asset.exchange ? ` - ${item.asset.exchange}` : ""}
          </p>
          {latestImpact ? (
            <div className="mt-3">
              <div className="flex items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${directionTone}`}>
                  {latestImpact.impact_direction}
                </span>
                <span className="text-[11px] uppercase tracking-wide text-gray-500">
                  {latestImpact.event_type.replace(/_/g, " ")}
                </span>
              </div>
              <p className="mt-1 text-sm text-gray-700">{latestImpact.event_title}</p>
              {latestImpact.published_at ? (
                <p className="mt-1 text-xs text-gray-400">
                  {formatDistanceToNow(new Date(latestImpact.published_at), { addSuffix: true })}
                </p>
              ) : null}
            </div>
          ) : (
            <p className="mt-3 text-sm text-gray-500">No linked event impacts yet.</p>
          )}
        </div>
        <button
          onClick={() => onDelete(item.id)}
          className="inline-flex items-center gap-1 self-start rounded-full border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-700"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Remove
        </button>
      </div>
    </div>
  );
}
