"use client";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutGrid, Plus, Sparkles } from "lucide-react";
import { BoardCreatePanel } from "@/components/BoardCreatePanel";
import { BoardCard } from "@/components/BoardCard";
import { MasonryGrid } from "@/components/MasonryGrid";
import {
  createBoardFromTemplate,
  fetchBoardTemplates,
  fetchMyBoards,
  fetchPublicBoards,
  type BoardTemplate,
} from "@/lib/api";

export default function BoardsPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [isAuthed, setIsAuthed] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setIsAuthed(Boolean(localStorage.getItem("access_token")));
    }
  }, []);

  const { data: boards, isLoading } = useQuery({
    queryKey: ["boards", "public"],
    queryFn: () => fetchPublicBoards(60),
  });
  const { data: myBoards, isLoading: isMyBoardsLoading } = useQuery({
    queryKey: ["boards", "mine"],
    queryFn: fetchMyBoards,
    enabled: isAuthed,
  });
  const { data: templates } = useQuery({
    queryKey: ["boards", "templates"],
    queryFn: fetchBoardTemplates,
  });

  const templateMutation = useMutation({
    mutationFn: ({ slug, visibility }: { slug: string; visibility: "public" | "private" }) =>
      createBoardFromTemplate(slug, visibility),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["boards", "mine"] });
      await queryClient.invalidateQueries({ queryKey: ["boards", "public"] });
    },
  });

  return (
    <div className="max-w-screen-2xl mx-auto px-4 py-6">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <LayoutGrid className="w-5 h-5 text-geo-500" />
          <h1 className="text-lg font-bold text-gray-900">Intelligence Boards</h1>
        </div>
        <button
          onClick={() => setShowCreate((value) => !value)}
          className="flex items-center gap-1.5 rounded-full bg-geo-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-all hover:bg-geo-600 active:scale-95"
        >
          <Plus className="w-4 h-4" />
          {showCreate ? "Close" : "New Board"}
        </button>
      </div>

      {isAuthed && showCreate ? (
        <div className="mb-6">
          <BoardCreatePanel onCreated={() => setShowCreate(false)} />
        </div>
      ) : null}

      <section className="mb-8 rounded-[28px] border border-gray-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-geo-500" />
          <h2 className="text-sm font-semibold text-gray-900">Example Boards</h2>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          {(templates ?? []).map((template) => (
            <TemplateCard
              key={template.slug}
              template={template}
              isAuthed={isAuthed}
              isPending={templateMutation.isPending}
              onCreate={(visibility) => templateMutation.mutate({ slug: template.slug, visibility })}
            />
          ))}
        </div>
      </section>

      {isAuthed ? (
        <section className="mb-8">
          <div className="mb-3 flex items-center gap-2">
            <LayoutGrid className="w-4 h-4 text-geo-500" />
            <h2 className="text-sm font-semibold text-gray-900">Your Boards</h2>
          </div>
          {isMyBoardsLoading ? (
            <MasonryGrid>
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="mb-4 h-44 rounded-[var(--pin-radius)] skeleton" />
              ))}
            </MasonryGrid>
          ) : myBoards && myBoards.length > 0 ? (
            <MasonryGrid>
              {myBoards.map((board) => (
                <BoardCard key={board.id} board={board} />
              ))}
            </MasonryGrid>
          ) : (
            <div className="rounded-2xl border border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
              No personal boards yet.
            </div>
          )}
        </section>
      ) : null}

      <div className="mb-3 flex items-center gap-2">
        <LayoutGrid className="w-4 h-4 text-geo-500" />
        <h2 className="text-sm font-semibold text-gray-900">Public Boards</h2>
      </div>

      {isLoading ? (
        <MasonryGrid>
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="mb-4 h-52 rounded-[var(--pin-radius)] skeleton" />
          ))}
        </MasonryGrid>
      ) : boards && boards.length > 0 ? (
        <MasonryGrid>
          {boards.map((board) => (
            <BoardCard key={board.id} board={board} />
          ))}
        </MasonryGrid>
      ) : (
        <div className="flex flex-col items-center justify-center py-32 text-center">
          <LayoutGrid className="mb-4 h-14 w-14 text-gray-200" />
          <h2 className="mb-2 text-xl font-semibold text-gray-500">No boards yet</h2>
          <p className="max-w-xs text-sm text-gray-400">
            Create your first intelligence board to start organizing events and predictions.
          </p>
        </div>
      )}
    </div>
  );
}

function TemplateCard({
  template,
  isAuthed,
  isPending,
  onCreate,
}: {
  template: BoardTemplate;
  isAuthed: boolean;
  isPending: boolean;
  onCreate: (visibility: "public" | "private") => void;
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
      <h3 className="text-sm font-semibold text-gray-900">{template.title}</h3>
      <p className="mt-2 text-sm text-gray-500">{template.description}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          onClick={() => onCreate("private")}
          disabled={!isAuthed || isPending}
          className="rounded-full bg-gray-900 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
        >
          Create Private
        </button>
        <button
          onClick={() => onCreate("public")}
          disabled={!isAuthed || isPending}
          className="rounded-full border border-gray-300 px-4 py-2 text-xs font-semibold text-gray-700 disabled:opacity-50"
        >
          Create Public
        </button>
      </div>
      {!isAuthed ? <p className="mt-3 text-xs text-amber-700">Login required to create from template.</p> : null}
    </div>
  );
}
