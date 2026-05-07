"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";

import { BoardCreatePanel } from "@/components/BoardCreatePanel";
import { createPin, fetchMyBoards, type Pin } from "@/lib/api";

function getErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Request failed.";
}

export function SaveToBoardDialog({
  open,
  contentId,
  contentType,
  suggestedNote,
  onClose,
}: {
  open: boolean;
  contentId: string;
  contentType: Pin["content_type"];
  suggestedNote?: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [selectedBoardId, setSelectedBoardId] = useState("");
  const [note, setNote] = useState(suggestedNote ?? "");
  const [showCreateBoard, setShowCreateBoard] = useState(false);

  const isAuthed =
    typeof window !== "undefined" && Boolean(window.localStorage.getItem("access_token"));

  const boardsQuery = useQuery({
    queryKey: ["boards", "mine"],
    queryFn: fetchMyBoards,
    enabled: open && isAuthed,
  });

  const saveMutation = useMutation({
    mutationFn: createPin,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["pins"] });
      await queryClient.invalidateQueries({ queryKey: ["boards", "mine"] });
      setSelectedBoardId("");
      setNote(suggestedNote ?? "");
      onClose();
    },
  });

  const boards = useMemo(() => boardsQuery.data ?? [], [boardsQuery.data]);

  useEffect(() => {
    if (open) {
      setSelectedBoardId("");
      setNote(suggestedNote ?? "");
    }
  }, [open, suggestedNote]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/35 px-4">
      <div className="w-full max-w-2xl rounded-[28px] border border-gray-200 bg-white p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Save To Board</h2>
            <p className="mt-1 text-sm text-gray-500">
              Save this {contentType} to an existing board or create a new one.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-full border border-gray-200 p-2 text-gray-500"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {!isAuthed ? (
          <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Login required to save items to boards.
          </div>
        ) : (
          <>
            <div className="mt-5 rounded-2xl border border-gray-200 bg-gray-50 p-4">
              <label className="block text-sm font-semibold text-gray-900">Choose board</label>
              <select
                value={selectedBoardId}
                onChange={(event) => setSelectedBoardId(event.target.value)}
                className="mt-2 h-10 w-full rounded-full border border-gray-300 bg-white px-4 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
              >
                <option value="">Select a board</option>
                {boards.map((board) => (
                  <option key={board.id} value={board.id}>
                    {board.title} ({board.visibility})
                  </option>
                ))}
              </select>
              <label className="mt-4 block text-sm font-semibold text-gray-900">Note</label>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
                className="mt-2 w-full rounded-2xl border border-gray-300 px-4 py-3 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-geo-300"
                placeholder="Optional note"
              />
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <button
                  onClick={() =>
                    saveMutation.mutate({
                      board_id: selectedBoardId,
                      content_type: contentType,
                      content_id: contentId,
                      note: note.trim() || undefined,
                    })
                  }
                  disabled={!selectedBoardId || saveMutation.isPending}
                  className="rounded-full bg-gray-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                >
                  Save Pin
                </button>
                <button
                  onClick={() => setShowCreateBoard((value) => !value)}
                  className="rounded-full border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700"
                >
                  {showCreateBoard ? "Hide Board Form" : "Create New Board"}
                </button>
              </div>
              {saveMutation.isError ? (
                <p className="mt-3 text-sm text-red-700">{getErrorMessage(saveMutation.error)}</p>
              ) : null}
            </div>

            {showCreateBoard ? (
              <div className="mt-4">
                <BoardCreatePanel compact onCreated={() => setShowCreateBoard(false)} />
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
