"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { createBoard } from "@/lib/api";

function getErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Request failed.";
}

export function BoardCreatePanel({
  onCreated,
  compact = false,
}: {
  onCreated?: () => void;
  compact?: boolean;
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<"public" | "private">("private");

  const mutation = useMutation({
    mutationFn: createBoard,
    onSuccess: async () => {
      setTitle("");
      setDescription("");
      setVisibility("private");
      await queryClient.invalidateQueries({ queryKey: ["boards", "mine"] });
      await queryClient.invalidateQueries({ queryKey: ["boards", "public"] });
      onCreated?.();
    },
  });

  return (
    <div className={`rounded-2xl border border-gray-200 bg-white ${compact ? "p-4" : "p-5"} shadow-sm`}>
      <h2 className="text-sm font-semibold text-gray-900">Create Board</h2>
      <div className={`mt-3 grid gap-3 ${compact ? "" : "md:grid-cols-[1.4fr_1.6fr_160px_auto]"}`}>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Board title"
          className="h-10 rounded-full border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
        />
        <input
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Short description"
          className="h-10 rounded-full border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
        />
        <select
          value={visibility}
          onChange={(event) => setVisibility(event.target.value as "public" | "private")}
          className="h-10 rounded-full border border-gray-300 px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
        >
          <option value="private">Private</option>
          <option value="public">Public</option>
        </select>
        <button
          onClick={() =>
            mutation.mutate({
              title: title.trim(),
              description: description.trim() || undefined,
              visibility,
            })
          }
          disabled={mutation.isPending || !title.trim()}
          className="inline-flex h-10 items-center justify-center gap-1 rounded-full bg-gray-900 px-4 text-sm font-semibold text-white disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Create
        </button>
      </div>
      {mutation.isError ? (
        <p className="mt-3 text-sm text-red-700">{getErrorMessage(mutation.error)}</p>
      ) : null}
    </div>
  );
}
