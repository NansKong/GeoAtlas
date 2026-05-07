"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GripVertical, Plus, Save, Trash2 } from "lucide-react";

import {
  createPin,
  deletePin,
  fetchBoardById,
  fetchBoardPins,
  reorderBoardPins,
  type Pin,
  updatePin,
} from "@/lib/api";

const CONTENT_TYPES: Array<Pin["content_type"]> = ["event", "asset", "prediction", "news"];

function moveItem<T>(items: T[], fromIndex: number, toIndex: number): T[] {
  const next = [...items];
  const [item] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, item);
  return next;
}

export default function BoardDetailPage() {
  const params = useParams<{ id: string }>();
  const boardId = String(params?.id ?? "");
  const queryClient = useQueryClient();

  const [contentType, setContentType] = useState<Pin["content_type"]>("event");
  const [contentId, setContentId] = useState("");
  const [note, setNote] = useState("");
  const [editingPinId, setEditingPinId] = useState<string | null>(null);
  const [editingNote, setEditingNote] = useState("");
  const [isAuthed, setIsAuthed] = useState(false);
  const [orderedPins, setOrderedPins] = useState<Pin[]>([]);
  const [draggingPinId, setDraggingPinId] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setIsAuthed(Boolean(localStorage.getItem("access_token")));
    }
  }, []);

  const boardQuery = useQuery({
    queryKey: ["board", boardId],
    queryFn: () => fetchBoardById(boardId),
    enabled: Boolean(boardId),
  });

  const pinsQuery = useQuery({
    queryKey: ["pins", boardId],
    queryFn: () => fetchBoardPins(boardId),
    enabled: Boolean(boardId),
  });

  useEffect(() => {
    setOrderedPins((pinsQuery.data ?? []).slice().sort((a, b) => a.position - b.position));
  }, [pinsQuery.data]);

  const createPinMutation = useMutation({
    mutationFn: createPin,
    onSuccess: async () => {
      setContentId("");
      setNote("");
      await queryClient.invalidateQueries({ queryKey: ["pins", boardId] });
      await queryClient.invalidateQueries({ queryKey: ["board", boardId] });
      await queryClient.invalidateQueries({ queryKey: ["boards", "mine"] });
    },
  });

  const deletePinMutation = useMutation({
    mutationFn: deletePin,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["pins", boardId] });
      await queryClient.invalidateQueries({ queryKey: ["board", boardId] });
      await queryClient.invalidateQueries({ queryKey: ["boards", "mine"] });
    },
  });

  const updatePinMutation = useMutation({
    mutationFn: ({ pinId, value }: { pinId: string; value: string }) => updatePin(pinId, { note: value }),
    onSuccess: async () => {
      setEditingPinId(null);
      setEditingNote("");
      await queryClient.invalidateQueries({ queryKey: ["pins", boardId] });
    },
  });

  const reorderMutation = useMutation({
    mutationFn: (pinIds: string[]) => reorderBoardPins(boardId, { pin_ids: pinIds }),
    onMutate: async (pinIds) => {
      setOrderedPins((current) =>
        pinIds
          .map((pinId) => current.find((item) => item.id === pinId))
          .filter((item): item is Pin => Boolean(item))
      );
    },
    onError: async () => {
      await queryClient.invalidateQueries({ queryKey: ["pins", boardId] });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["pins", boardId] });
      await queryClient.invalidateQueries({ queryKey: ["board", boardId] });
      await queryClient.invalidateQueries({ queryKey: ["boards", "mine"] });
    },
  });

  const pins = useMemo(() => orderedPins, [orderedPins]);

  return (
    <div className="mx-auto max-w-screen-xl px-4 py-6">
      {boardQuery.isLoading ? (
        <div className="h-24 animate-pulse rounded-2xl border border-gray-200 bg-gray-100" />
      ) : boardQuery.isError || !boardQuery.data ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Unable to load board. Make sure the board exists and you have access.
        </div>
      ) : (
        <div className="rounded-2xl border border-gray-200 bg-white p-4">
          <h1 className="text-xl font-bold text-gray-900">{boardQuery.data.title}</h1>
          {boardQuery.data.description ? (
            <p className="mt-1 text-sm text-gray-500">{boardQuery.data.description}</p>
          ) : null}
          <p className="mt-2 text-xs text-gray-400">
            {boardQuery.data.pin_count} pins � {boardQuery.data.visibility}
          </p>
        </div>
      )}

      <section className="mt-5 rounded-2xl border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-gray-900">Add Pin</h2>
        <div className="mt-3 grid gap-2 md:grid-cols-[160px_1fr_1fr_auto]">
          <select
            value={contentType}
            onChange={(e) => setContentType(e.target.value as Pin["content_type"])}
            className="h-10 rounded-lg border border-gray-300 px-3 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
          >
            {CONTENT_TYPES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <input
            value={contentId}
            onChange={(e) => setContentId(e.target.value)}
            placeholder="Content UUID"
            className="h-10 rounded-lg border border-gray-300 px-3 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
          />
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional note"
            className="h-10 rounded-lg border border-gray-300 px-3 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
          />
          <button
            onClick={() => {
              if (!contentId.trim() || !boardId) return;
              createPinMutation.mutate({
                board_id: boardId,
                content_type: contentType,
                content_id: contentId.trim(),
                note: note.trim() || undefined,
              });
            }}
            disabled={!isAuthed || createPinMutation.isPending || !contentId.trim()}
            className="inline-flex h-10 items-center gap-1 rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            Add
          </button>
        </div>
        <p className="mt-2 text-xs text-gray-400">Drag cards below to reorder the board.</p>
        {!isAuthed ? (
          <p className="mt-2 text-xs text-amber-700">Login required to add, edit, delete, or reorder pins.</p>
        ) : null}
      </section>

      <section className="mt-5 space-y-3">
        {pinsQuery.isLoading ? (
          <div className="h-28 animate-pulse rounded-2xl border border-gray-200 bg-gray-100" />
        ) : pins.length === 0 ? (
          <div className="rounded-2xl border border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
            No pins yet for this board.
          </div>
        ) : (
          pins.map((pin, index) => (
            <div
              key={pin.id}
              draggable={isAuthed}
              onDragStart={() => setDraggingPinId(pin.id)}
              onDragOver={(event) => {
                event.preventDefault();
                if (!draggingPinId || draggingPinId === pin.id) return;
                const fromIndex = orderedPins.findIndex((item) => item.id === draggingPinId);
                const toIndex = orderedPins.findIndex((item) => item.id === pin.id);
                if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) return;
                setOrderedPins((current) => moveItem(current, fromIndex, toIndex));
              }}
              onDragEnd={() => {
                if (!draggingPinId) return;
                setDraggingPinId(null);
                const nextIds = orderedPins.map((item) => item.id);
                const sourceIds = (pinsQuery.data ?? []).slice().sort((a, b) => a.position - b.position).map((item) => item.id);
                if (JSON.stringify(nextIds) !== JSON.stringify(sourceIds)) {
                  reorderMutation.mutate(nextIds);
                }
              }}
              className={`rounded-2xl border bg-white p-4 shadow-sm transition ${
                draggingPinId === pin.id ? "border-geo-300 opacity-70" : "border-gray-200"
              }`}
            >
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-gray-500">
                    <GripVertical className="h-4 w-4" />
                    <span>{index + 1}</span>
                    <span>{pin.content_type}</span>
                  </div>
                  <p className="mt-2 truncate font-mono text-xs text-gray-700">{pin.content_id}</p>
                  {editingPinId === pin.id ? (
                    <input
                      value={editingNote}
                      onChange={(e) => setEditingNote(e.target.value)}
                      className="mt-2 h-9 w-full rounded-lg border border-gray-300 px-2 text-sm text-gray-900 md:w-[420px]"
                    />
                  ) : (
                    <p className="mt-2 text-sm text-gray-500">{pin.note || "No note"}</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {editingPinId === pin.id ? (
                    <button
                      onClick={() => updatePinMutation.mutate({ pinId: pin.id, value: editingNote })}
                      disabled={!isAuthed || updatePinMutation.isPending}
                      className="inline-flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 disabled:opacity-50"
                    >
                      <Save className="h-3.5 w-3.5" />
                      Save
                    </button>
                  ) : (
                    <button
                      onClick={() => {
                        setEditingPinId(pin.id);
                        setEditingNote(pin.note || "");
                      }}
                      disabled={!isAuthed}
                      className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 disabled:opacity-50"
                    >
                      Edit note
                    </button>
                  )}
                  <button
                    onClick={() => deletePinMutation.mutate(pin.id)}
                    disabled={!isAuthed || deletePinMutation.isPending}
                    className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
