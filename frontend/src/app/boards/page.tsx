"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, LayoutGrid, Plus, Sparkles } from "lucide-react";
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
    <div className="ga-shell">
      <section className="ga-hero"><span className="ga-eyebrow"><LayoutGrid size={15} /> YOUR INTELLIGENCE</span><h1>Make sense of<br />what you follow.</h1><p>Collect events and predictions into focused boards. Start with a theme or build your own view.</p></section>
      <div className="ga-section-head ga-section">
        <div><span className="ga-eyebrow">GET ORGANIZED</span><h2>Intelligence boards</h2><p>Public boards are open to everyone. Sign in to save your own.</p></div>
        {isAuthed ? <button
          onClick={() => setShowCreate((value) => !value)}
          className="ga-button ga-button-primary"
        >
          <Plus className="w-4 h-4" />
          {showCreate ? "Close" : "New Board"}
        </button> : <Link href="/login" className="ga-button ga-button-primary">Sign in to create <ArrowRight size={16} /></Link>}
      </div>

      {isAuthed && showCreate ? (
        <div className="mb-6">
          <BoardCreatePanel onCreated={() => setShowCreate(false)} />
        </div>
      ) : null}

      <section className="mb-8 ga-panel p-5">
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
      ) : <div className="ga-empty"><LayoutGrid className="mx-auto mb-4 text-emerald-600" size={28} /><h2>No public boards yet</h2><p>Browse the examples above for ideas. {isAuthed ? "You can also create the first public board." : "Sign in to publish your own."}</p></div>}
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
        {isAuthed ? <><button
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
        </button></> : <Link href="/login" className="ga-text-link">Sign in to use this template <ArrowRight size={15} /></Link>}
      </div>
    </div>
  );
}
