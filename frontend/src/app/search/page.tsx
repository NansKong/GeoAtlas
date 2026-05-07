"use client";

import { Suspense, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { EventPin, type EventPinData } from "@/components/EventPin";
import { MasonryGrid } from "@/components/MasonryGrid";
import { SaveToBoardDialog } from "@/components/SaveToBoardDialog";
import { fetchEvents } from "@/lib/api";

export default function SearchPage() {
  return (
    <Suspense fallback={<SearchPageLoading />}>
      <SearchPageContent />
    </Suspense>
  );
}

function SearchPageContent() {
  const params = useSearchParams();
  const query = useMemo(() => (params.get("q") || "").trim(), [params]);
  const [saveTarget, setSaveTarget] = useState<EventPinData | null>(null);

  const { data: events, isLoading } = useQuery({
    queryKey: ["search-events", query],
    queryFn: () => fetchEvents({ q: query || undefined, limit: 100 }),
  });

  return (
    <div className="max-w-screen-2xl mx-auto px-4 py-6">
      <SaveToBoardDialog
        open={saveTarget !== null}
        contentId={saveTarget?.id ?? ""}
        contentType="event"
        suggestedNote={saveTarget ? `${saveTarget.event_type.replace(/_/g, " ")} - ${saveTarget.title}` : ""}
        onClose={() => setSaveTarget(null)}
      />

      <div className="flex items-center gap-2 mb-5">
        <Search className="w-5 h-5 text-geo-600" />
        <h1 className="text-lg font-bold text-gray-900">
          Search Results{query ? `: ${query}` : ""}
        </h1>
      </div>

      {isLoading ? (
        <MasonryGrid>
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="skeleton rounded-[var(--pin-radius)] mb-4" style={{ height: `${140 + (i % 4) * 40}px` }} />
          ))}
        </MasonryGrid>
      ) : events && events.length > 0 ? (
        <MasonryGrid>
          {events.map((event) => (
            <EventPin key={event.id} event={event} onSave={setSaveTarget} />
          ))}
        </MasonryGrid>
      ) : (
        <div className="rounded-2xl border border-gray-200 bg-white px-4 py-8 text-sm text-gray-500">
          No events found for this topic.
        </div>
      )}
    </div>
  );
}

function SearchPageLoading() {
  return (
    <div className="max-w-screen-2xl mx-auto px-4 py-6">
      <div className="flex items-center gap-2 mb-5">
        <Search className="w-5 h-5 text-geo-600" />
        <h1 className="text-lg font-bold text-gray-900">Search Results</h1>
      </div>
      <MasonryGrid>
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            className="skeleton rounded-[var(--pin-radius)] mb-4"
            style={{ height: `${140 + (i % 4) * 40}px` }}
          />
        ))}
      </MasonryGrid>
    </div>
  );
}
