"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileText, Globe2, ShieldAlert, XCircle } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

import {
  approveReviewEvent,
  editPendingReviewEvent,
  fetchMe,
  fetchPendingReviewEvents,
  rejectReviewEvent,
  type EventReviewItem,
  type ReviewDecisionInput,
} from "@/lib/api";

const EVENT_TYPES = [
  "conflict",
  "sanction",
  "trade_policy",
  "energy_disruption",
  "election",
  "regulation",
  "economic_data",
];

type ReviewFormState = {
  title: string;
  description: string;
  event_type: string;
  country: string;
  region: string;
  severity: number;
  confidence_score: number;
};

function toFormState(item: EventReviewItem): ReviewFormState {
  return {
    title: item.title,
    description: item.description ?? "",
    event_type: item.event_type,
    country: item.country ?? "",
    region: item.region ?? "",
    severity: item.severity ?? 3,
    confidence_score: Number((item.confidence_score ?? 0.6).toFixed(2)),
  };
}

export default function ReviewQueuePage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<ReviewFormState | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    retry: false,
  });

  const queueQuery = useQuery({
    queryKey: ["review-queue"],
    queryFn: () => fetchPendingReviewEvents(60),
    enabled: meQuery.isSuccess,
  });

  const queue = queueQuery.data ?? [];
  const selected = useMemo(
    () => queue.find((item) => item.id === selectedId) ?? queue[0] ?? null,
    [queue, selectedId]
  );

  useEffect(() => {
    if (!selected) {
      setForm(null);
      return;
    }
    setSelectedId(selected.id);
    setForm(toFormState(selected));
  }, [selected?.id]);

  const refreshQueue = async () => {
    await queryClient.invalidateQueries({ queryKey: ["review-queue"] });
  };

  const editMutation = useMutation({
    mutationFn: ({ eventId, payload }: { eventId: string; payload: ReviewDecisionInput }) =>
      editPendingReviewEvent(eventId, payload),
    onSuccess: async (updated) => {
      setFlash("Draft updated");
      await refreshQueue();
      setSelectedId(updated.id);
    },
  });

  const approveMutation = useMutation({
    mutationFn: ({ eventId, payload }: { eventId: string; payload: ReviewDecisionInput }) =>
      approveReviewEvent(eventId, payload),
    onSuccess: async () => {
      setFlash("Event approved");
      const nextQueue = queue.filter((item) => item.id !== selected?.id);
      await refreshQueue();
      setSelectedId(nextQueue[0]?.id ?? null);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (eventId: string) => rejectReviewEvent(eventId),
    onSuccess: async () => {
      setFlash("Event rejected");
      const nextQueue = queue.filter((item) => item.id !== selected?.id);
      await refreshQueue();
      setSelectedId(nextQueue[0]?.id ?? null);
    },
  });

  if (meQuery.isError) {
    return (
      <GateState
        title="Reviewer login required"
        detail="This page uses the authenticated review APIs. Sign in first, then reopen the review queue."
      />
    );
  }

  if (meQuery.isLoading || queueQuery.isLoading) {
    return (
      <div className="mx-auto max-w-screen-2xl px-4 py-6">
        <div className="grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, idx) => (
              <div key={idx} className="h-28 animate-pulse rounded-[28px] border border-gray-200 bg-gray-100" />
            ))}
          </div>
          <div className="h-[680px] animate-pulse rounded-[32px] border border-gray-200 bg-gray-100" />
        </div>
      </div>
    );
  }

  if (!queue.length || !selected || !form) {
    return (
      <GateState
        title="Review queue is clear"
        detail="No events are currently waiting for human review."
      />
    );
  }

  const isBusy = editMutation.isPending || approveMutation.isPending || rejectMutation.isPending;

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-geo-600" />
          <h1 className="text-lg font-bold text-gray-900">Human Review Queue</h1>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-600">
          <span>{queue.length} pending</span>
          <span className="text-gray-300">|</span>
          <span>{meQuery.data?.username}</span>
        </div>
      </div>

      {flash && (
        <div className="mb-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {flash}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="space-y-3">
          {queue.map((item) => (
            <button
              key={item.id}
              onClick={() => {
                setSelectedId(item.id);
                setForm(toFormState(item));
                setFlash(null);
              }}
              className={`w-full rounded-[28px] border px-4 py-4 text-left transition-all ${
                selected.id === item.id
                  ? "border-gray-900 bg-gray-900 text-white shadow-lg"
                  : "border-gray-200 bg-white text-gray-900 hover:border-gray-300 hover:bg-gray-50"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <span className="text-xs font-semibold uppercase tracking-wide opacity-75">
                  {item.event_type.replace(/_/g, " ")}
                </span>
                {item.confidence_score !== undefined && (
                  <span className="text-xs font-medium opacity-75">
                    {Math.round(item.confidence_score * 100)}%
                  </span>
                )}
              </div>
              <h2 className="mt-2 line-clamp-3 text-sm font-semibold leading-snug">{item.title}</h2>
              <div className="mt-3 flex items-center gap-2 text-xs opacity-75">
                {item.country && <span>{item.country}</span>}
                {item.published_at && (
                  <span>{formatDistanceToNow(new Date(item.published_at), { addSuffix: true })}</span>
                )}
              </div>
            </button>
          ))}
        </aside>

        <section className="rounded-[32px] border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Extracted event</p>
              <h2 className="mt-1 text-2xl font-bold text-gray-900">{selected.title}</h2>
            </div>
            <div className="grid gap-2 text-right text-sm text-gray-500">
              <span>Status: {selected.status}</span>
              <span>Severity: {selected.severity ?? "-"}</span>
              <span>Confidence: {selected.confidence_score ? `${Math.round(selected.confidence_score * 100)}%` : "-"}</span>
            </div>
          </div>

          <div className="mb-6 grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="space-y-5">
              <Field label="Title">
                <input
                  value={form.title}
                  onChange={(e) => setForm((current) => current ? { ...current, title: e.target.value } : current)}
                  className="h-11 w-full rounded-2xl border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
                />
              </Field>

              <Field label="Description">
                <textarea
                  value={form.description}
                  onChange={(e) => setForm((current) => current ? { ...current, description: e.target.value } : current)}
                  rows={6}
                  className="w-full rounded-2xl border border-gray-300 px-4 py-3 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
                />
              </Field>

              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Event Type">
                  <select
                    value={form.event_type}
                    onChange={(e) => setForm((current) => current ? { ...current, event_type: e.target.value } : current)}
                    className="h-11 w-full rounded-2xl border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
                  >
                    {EVENT_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type.replace(/_/g, " ")}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Severity">
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={form.severity}
                    onChange={(e) =>
                      setForm((current) =>
                        current ? { ...current, severity: Math.max(1, Math.min(5, Number(e.target.value) || 1)) } : current
                      )
                    }
                    className="h-11 w-full rounded-2xl border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
                  />
                </Field>
                <Field label="Country">
                  <input
                    value={form.country}
                    onChange={(e) => setForm((current) => current ? { ...current, country: e.target.value } : current)}
                    className="h-11 w-full rounded-2xl border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
                  />
                </Field>
                <Field label="Region">
                  <input
                    value={form.region}
                    onChange={(e) => setForm((current) => current ? { ...current, region: e.target.value } : current)}
                    className="h-11 w-full rounded-2xl border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
                  />
                </Field>
                <Field label="Confidence Score">
                  <input
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={form.confidence_score}
                    onChange={(e) =>
                      setForm((current) =>
                        current
                          ? {
                              ...current,
                              confidence_score: Math.max(0, Math.min(1, Number(e.target.value) || 0)),
                            }
                          : current
                      )
                    }
                    className="h-11 w-full rounded-2xl border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
                  />
                </Field>
              </div>
            </div>

            <div className="space-y-4">
              <ContextCard icon={<Globe2 className="h-4 w-4 text-geo-700" />} title="Entity tags">
                <div className="flex flex-wrap gap-2">
                  {selected.tags.length > 0 ? (
                    selected.tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-700"
                      >
                        {tag}
                      </span>
                    ))
                  ) : (
                    <p className="text-sm text-gray-400">No tags extracted yet.</p>
                  )}
                </div>
              </ContextCard>

              <ContextCard icon={<AlertTriangle className="h-4 w-4 text-geo-700" />} title="Suggested impact">
                <div className="space-y-2">
                  {selected.affected_assets.length > 0 ? (
                    selected.affected_assets.map((asset) => (
                      <div key={asset.ticker} className="flex items-center justify-between rounded-2xl bg-gray-50 px-3 py-2">
                        <div>
                          <p className="text-sm font-semibold text-gray-900">{asset.ticker}</p>
                          {asset.name && <p className="text-xs text-gray-500">{asset.name}</p>}
                        </div>
                        <div className="text-right">
                          <p className="text-xs font-semibold uppercase text-gray-600">{asset.impact_direction}</p>
                          {asset.confidence_score !== undefined && (
                            <p className="text-xs text-gray-500">{Math.round(asset.confidence_score * 100)}%</p>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="text-sm text-gray-400">No affected assets suggested yet.</p>
                  )}
                </div>
              </ContextCard>

              <ContextCard icon={<FileText className="h-4 w-4 text-geo-700" />} title="Source articles">
                <div className="space-y-3">
                  {selected.articles.map((article) => (
                    <a
                      key={article.id}
                      href={article.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block rounded-2xl border border-gray-200 px-3 py-3 hover:bg-gray-50"
                    >
                      <p className="text-sm font-semibold text-gray-900">{article.title}</p>
                      <p className="mt-1 text-xs text-gray-500">
                        {article.source}
                        {article.published_at &&
                          ` · ${formatDistanceToNow(new Date(article.published_at), { addSuffix: true })}`}
                      </p>
                    </a>
                  ))}
                </div>
              </ContextCard>
            </div>
          </div>

          <div className="flex flex-wrap gap-3 border-t border-gray-200 pt-5">
            <button
              onClick={() =>
                editMutation.mutate({
                  eventId: selected.id,
                  payload: buildPayload(form),
                })
              }
              disabled={isBusy}
              className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Save Draft
            </button>
            <button
              onClick={() =>
                approveMutation.mutate({
                  eventId: selected.id,
                  payload: buildPayload(form),
                })
              }
              disabled={isBusy}
              className="inline-flex items-center gap-2 rounded-full bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <CheckCircle2 className="h-4 w-4" />
              Approve
            </button>
            <button
              onClick={() => rejectMutation.mutate(selected.id)}
              disabled={isBusy}
              className="inline-flex items-center gap-2 rounded-full bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <XCircle className="h-4 w-4" />
              Reject
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function buildPayload(form: ReviewFormState): ReviewDecisionInput {
  return {
    title: form.title.trim(),
    description: form.description.trim() || undefined,
    event_type: form.event_type,
    country: form.country.trim() || undefined,
    region: form.region.trim() || undefined,
    severity: form.severity,
    confidence_score: Number(form.confidence_score.toFixed(2)),
  };
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</span>
      {children}
    </label>
  );
}

function ContextCard({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-[28px] border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        {icon}
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function GateState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-2xl flex-col items-center justify-center px-4 text-center">
      <ShieldAlert className="mb-4 h-14 w-14 text-gray-200" />
      <h1 className="text-xl font-semibold text-gray-600">{title}</h1>
      <p className="mt-2 text-sm text-gray-400">{detail}</p>
    </div>
  );
}
