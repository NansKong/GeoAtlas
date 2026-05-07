"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Plus, Trash2 } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

import {
  createAlert,
  deleteAlert,
  fetchAlertPreferences,
  fetchAlerts,
  updateAlert,
  updateAlertPreferences,
  type AlertRule,
} from "@/lib/api";

const EVENT_TYPES = [
  { value: "", label: "Any event type" },
  { value: "conflict", label: "Conflict" },
  { value: "sanction", label: "Sanction" },
  { value: "trade_policy", label: "Trade Policy" },
  { value: "economic_data", label: "Economic Data" },
  { value: "energy_disruption", label: "Energy Disruption" },
  { value: "election", label: "Election" },
  { value: "regulation", label: "Regulation" },
];

function getErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Request failed.";
}

export default function AlertsPage() {
  const queryClient = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [eventType, setEventType] = useState("");
  const [threshold, setThreshold] = useState("");
  const [tokensText, setTokensText] = useState("");
  const [isAuthed, setIsAuthed] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setIsAuthed(Boolean(localStorage.getItem("access_token")));
    }
  }, []);

  const alertsQuery = useQuery({
    queryKey: ["alerts"],
    queryFn: fetchAlerts,
    enabled: isAuthed,
  });

  const preferencesQuery = useQuery({
    queryKey: ["alert-preferences"],
    queryFn: fetchAlertPreferences,
    enabled: isAuthed,
  });

  useEffect(() => {
    if (preferencesQuery.data) {
      setTokensText(preferencesQuery.data.web_push_tokens.join("\n"));
    }
  }, [preferencesQuery.data]);

  const createMutation = useMutation({
    mutationFn: createAlert,
    onSuccess: async () => {
      setTicker("");
      setEventType("");
      setThreshold("");
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ alertId, isActive }: { alertId: string; isActive: boolean }) =>
      updateAlert(alertId, { is_active: isActive }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAlert,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  const preferencesMutation = useMutation({
    mutationFn: updateAlertPreferences,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["alert-preferences"] });
    },
  });

  const alerts = useMemo(() => alertsQuery.data ?? [], [alertsQuery.data]);

  return (
    <div className="mx-auto max-w-screen-xl px-4 py-6">
      <div className="flex items-center gap-2">
        <Bell className="h-5 w-5 text-geo-600" />
        <h1 className="text-xl font-bold text-gray-900">Alert Rules</h1>
      </div>
      <p className="mt-2 max-w-3xl text-sm text-gray-500">
        Get notified when geopolitical events match your asset or event-type rules. Delivery via email (SendGrid) and web push (Firebase FCM).
      </p>

      <section className="mt-6 rounded-[28px] border border-gray-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-gray-900">Delivery Preferences</h2>
        <div className="mt-4 grid gap-4 lg:grid-cols-[180px_180px_1fr]">
          <label className="flex items-center justify-between rounded-2xl border border-gray-200 px-4 py-3 text-sm text-gray-700">
            <span>Email delivery</span>
            <input
              type="checkbox"
              checked={preferencesQuery.data?.email_enabled ?? true}
              disabled={!isAuthed || preferencesMutation.isPending}
              onChange={(event) =>
                preferencesMutation.mutate({ email_enabled: event.target.checked })
              }
            />
          </label>
          <label className="flex items-center justify-between rounded-2xl border border-gray-200 px-4 py-3 text-sm text-gray-700">
            <span>Web push</span>
            <input
              type="checkbox"
              checked={preferencesQuery.data?.web_push_enabled ?? false}
              disabled={!isAuthed || preferencesMutation.isPending}
              onChange={(event) =>
                preferencesMutation.mutate({ web_push_enabled: event.target.checked })
              }
            />
          </label>
          <div className="rounded-2xl border border-gray-200 p-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <span>
                Email: {preferencesQuery.data?.email_delivery_ready ? "configured" : "missing SendGrid config"}
              </span>
              <span>
                Web push: {preferencesQuery.data?.web_push_delivery_ready ? "configured" : "missing FCM config"}
              </span>
            </div>
            <textarea
              value={tokensText}
              onChange={(event) => setTokensText(event.target.value)}
              rows={4}
              disabled={!isAuthed}
              placeholder="One FCM web push token per line"
              className="mt-3 w-full rounded-2xl border border-gray-300 px-4 py-3 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
            />
            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={() =>
                  preferencesMutation.mutate({
                    web_push_tokens: tokensText
                      .split(/\r?\n|,/)
                      .map((token) => token.trim())
                      .filter(Boolean),
                  })
                }
                disabled={!isAuthed || preferencesMutation.isPending}
                className="rounded-full bg-gray-900 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
              >
                Save Tokens
              </button>
              {preferencesMutation.isError ? (
                <p className="text-sm text-red-700">{getErrorMessage(preferencesMutation.error)}</p>
              ) : null}
            </div>
          </div>
        </div>
      </section>

      <section className="mt-6 rounded-[28px] border border-gray-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-gray-900">Create Rule</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_180px_auto]">
          <input
            value={ticker}
            onChange={(event) => setTicker(event.target.value.toUpperCase())}
            placeholder="Ticker, for example XOM"
            className="h-10 rounded-full border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
          />
          <select
            value={eventType}
            onChange={(event) => setEventType(event.target.value)}
            className="h-10 rounded-full border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
          >
            {EVENT_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <input
            value={threshold}
            onChange={(event) => setThreshold(event.target.value)}
            placeholder="Threshold"
            inputMode="decimal"
            className="h-10 rounded-full border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
          />
          <button
            onClick={() =>
              createMutation.mutate({
                ticker: ticker.trim() || undefined,
                event_type: eventType || undefined,
                threshold: threshold.trim() ? Number(threshold) : undefined,
                is_active: true,
              })
            }
            disabled={!isAuthed || createMutation.isPending || (!ticker.trim() && !eventType)}
            className="inline-flex h-10 items-center justify-center gap-1 rounded-full bg-gray-900 px-4 text-sm font-semibold text-white disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            Create
          </button>
        </div>
        {!isAuthed ? <p className="mt-3 text-sm text-amber-700">Login required to manage alert rules.</p> : null}
        {createMutation.isError ? <p className="mt-3 text-sm text-red-700">{getErrorMessage(createMutation.error)}</p> : null}
      </section>

      <section className="mt-6 space-y-3">
        {alertsQuery.isLoading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-24 animate-pulse rounded-2xl border border-gray-200 bg-gray-100" />
          ))
        ) : alerts.length > 0 ? (
          alerts.map((alert) => (
            <AlertRow
              key={alert.id}
              alert={alert}
              onToggle={(isActive) => toggleMutation.mutate({ alertId: alert.id, isActive })}
              onDelete={() => deleteMutation.mutate(alert.id)}
            />
          ))
        ) : (
          <div className="rounded-[28px] border border-dashed border-gray-200 bg-white px-6 py-16 text-center text-sm text-gray-500">
            No alert rules configured.
          </div>
        )}
      </section>
    </div>
  );
}

function AlertRow({
  alert,
  onToggle,
  onDelete,
}: {
  alert: AlertRule;
  onToggle: (isActive: boolean) => void;
  onDelete: () => void;
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            {alert.ticker ? (
              <span className="rounded-full bg-gray-900 px-2.5 py-1 text-xs font-bold text-white">{alert.ticker}</span>
            ) : null}
            {alert.event_type ? (
              <span className="rounded-full bg-geo-50 px-2.5 py-1 text-xs font-semibold text-geo-700">
                {alert.event_type.replace(/_/g, " ")}
              </span>
            ) : (
              <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-semibold text-gray-600">
                any event type
              </span>
            )}
            <span
              className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                alert.is_active ? "bg-emerald-100 text-emerald-800" : "bg-gray-100 text-gray-600"
              }`}
            >
              {alert.is_active ? "active" : "paused"}
            </span>
          </div>
          <p className="mt-2 text-sm text-gray-700">
            {alert.asset_name ?? "Any asset"}
            {alert.threshold !== undefined ? ` - threshold ${alert.threshold}` : ""}
          </p>
          <p className="mt-1 text-xs text-gray-400">
            Created {formatDistanceToNow(new Date(alert.created_at), { addSuffix: true })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onToggle(!alert.is_active)}
            className="rounded-full border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700"
          >
            {alert.is_active ? "Pause" : "Resume"}
          </button>
          <button
            onClick={onDelete}
            className="inline-flex items-center gap-1 rounded-full border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}
