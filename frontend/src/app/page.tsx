"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Globe, Newspaper, Search, Sparkles, Zap } from "lucide-react";

import { CrossAssetCorrelation } from "@/components/CrossAssetCorrelation";
import { EventPin, type EventPinData } from "@/components/EventPin";
import { GeoHeatmapWidget } from "@/components/GeoHeatmapWidget";
import { MasonryGrid } from "@/components/MasonryGrid";
import { MarketOverviewLayer } from "@/components/MarketOverviewLayer";
import { NewsFeedCard } from "@/components/NewsFeedCard";
import { PredictionCard } from "@/components/PredictionCard";
import { SaveToBoardDialog } from "@/components/SaveToBoardDialog";
import { WatchlistPanel } from "@/components/WatchlistPanel";
import { fetchEvents, fetchNews, fetchPredictions } from "@/lib/api";

const EVENT_TYPES = [
  { value: "", label: "All Events" },
  { value: "conflict", label: "Conflict" },
  { value: "sanction", label: "Sanctions" },
  { value: "trade_policy", label: "Trade" },
  { value: "energy_disruption", label: "Energy" },
  { value: "election", label: "Elections" },
  { value: "regulation", label: "Regulation" },
  { value: "economic_data", label: "Economic" },
];

const NEWS_CATEGORIES = [
  { value: "", label: "All News" },
  { value: "markets", label: "Markets" },
  { value: "economic_data", label: "Economy" },
  { value: "trade_policy", label: "Trade" },
  { value: "regulation", label: "Regulation" },
  { value: "energy_disruption", label: "Energy" },
  { value: "conflict", label: "Conflict" },
  { value: "election", label: "Elections" },
  { value: "sanction", label: "Sanctions" },
  { value: "general", label: "General" },
];

export default function HomePage() {
  const [activeType, setActiveType] = useState("");
  const [activeNewsCategory, setActiveNewsCategory] = useState("");
  const [topicQuery, setTopicQuery] = useState("");
  const [appliedTopicQuery, setAppliedTopicQuery] = useState("");
  const [saveTarget, setSaveTarget] = useState<EventPinData | null>(null);

  const { data: events, isLoading: isEventsLoading } = useQuery({
    queryKey: ["events", activeType, appliedTopicQuery],
    queryFn: () =>
      fetchEvents({
        event_type: activeType || undefined,
        q: appliedTopicQuery || undefined,
        status: "published",
        limit: 80,
      }),
  });

  const { data: articles, isLoading: isNewsLoading } = useQuery({
    queryKey: ["news-feed", activeNewsCategory, appliedTopicQuery],
    queryFn: () =>
      fetchNews({
        q: appliedTopicQuery || undefined,
        category: activeNewsCategory || undefined,
        limit: 24,
      }),
    staleTime: 60_000,
  });
  const { data: predictions, isLoading: isPredictionsLoading } = useQuery({
    queryKey: ["prediction-feed-preview"],
    queryFn: () => fetchPredictions({ published_only: true, limit: 4 }),
    staleTime: 30_000,
  });

  const eventCount = events?.length ?? 0;
  const articleCount = articles?.length ?? 0;

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-6">
      <SaveToBoardDialog
        open={saveTarget !== null}
        contentId={saveTarget?.id ?? ""}
        contentType="event"
        suggestedNote={saveTarget ? `${saveTarget.event_type.replace(/_/g, " ")} - ${saveTarget.title}` : ""}
        onClose={() => setSaveTarget(null)}
      />

      <div className="mb-6 flex items-center gap-3">
        <div className="flex items-center gap-2">
          <Zap className="h-5 w-5 text-geo-500" />
          <h1 className="text-lg font-bold text-gray-900">Global Intelligence Feed</h1>
        </div>
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-400">
          Live updates every 10 min
        </span>
      </div>

      <div className="mb-5 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            value={topicQuery}
            onChange={(e) => setTopicQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") setAppliedTopicQuery(topicQuery.trim());
            }}
            placeholder="Search any topic, country, source, ticker, company, sector..."
            className="h-10 w-full rounded-full border border-gray-300 bg-white pl-9 pr-4 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-geo-300"
          />
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setAppliedTopicQuery(topicQuery.trim())}
            className="h-10 rounded-full bg-gray-900 px-4 text-sm font-semibold text-white transition-colors hover:bg-gray-800"
          >
            Apply
          </button>
          <button
            onClick={() => {
              setTopicQuery("");
              setAppliedTopicQuery("");
              setActiveType("");
              setActiveNewsCategory("");
            }}
            className="h-10 rounded-full border border-gray-300 bg-white px-4 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-50"
          >
            Clear
          </button>
        </div>
      </div>

      <div className="mb-6 grid gap-3 md:grid-cols-2">
        <FeedStatCard
          icon={<Sparkles className="h-4 w-4 text-geo-700" />}
          title="Structured intelligence"
          value={`${eventCount} visible events`}
          detail="Auto-approved and human-approved events only"
        />
        <FeedStatCard
          icon={<Newspaper className="h-4 w-4 text-geo-700" />}
          title="Raw news stream"
          value={`${articleCount} categorized articles`}
          detail="Articles stay visible even before event extraction"
        />
      </div>

      <MarketOverviewLayer />
      <WatchlistPanel />

      <GeoHeatmapWidget />
      <CrossAssetCorrelation />

      <section className="mt-8">
        <div className="mb-3 flex items-center gap-2">
          <Zap className="h-5 w-5 text-geo-600" />
          <h2 className="text-base font-bold text-gray-900">Prediction Surface</h2>
          <span className="rounded-full bg-geo-50 px-2 py-0.5 text-xs font-medium text-geo-700">
            Accuracy-gated
          </span>
        </div>
        <p className="mb-4 max-w-3xl text-sm text-gray-500">
          Predictions are only surfaced when the event type clears the current back-test threshold. Everything else stays in the history view.
        </p>
        {isPredictionsLoading ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {Array.from({ length: 2 }).map((_, i) => (
              <div key={i} className="h-72 animate-pulse rounded-[26px] border border-gray-200 bg-gray-100" />
            ))}
          </div>
        ) : predictions && predictions.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {predictions.map((prediction) => (
              <PredictionCard key={prediction.id} prediction={prediction} />
            ))}
          </div>
        ) : (
          <SectionEmptyState
            icon={<Zap className="mb-4 h-12 w-12 text-gray-200" />}
            title="No live-eligible predictions yet"
            detail="Resolved accuracy needs to clear the production rule before predictions appear on the public surface."
          />
        )}
      </section>

      <section className="mt-8">
        <div className="mb-3 flex items-center gap-2">
          <Newspaper className="h-5 w-5 text-geo-600" />
          <h2 className="text-base font-bold text-gray-900">Live News Feed</h2>
          <span className="rounded-full bg-geo-50 px-2 py-0.5 text-xs font-medium text-geo-700">
            Categorized from raw articles
          </span>
        </div>
        <p className="mb-4 max-w-3xl text-sm text-gray-500">
          This section shows the raw feed directly, grouped by inferred category, so the homepage stays populated even
          when an article has not been promoted into a structured event yet.
        </p>
        <div className="mb-5 flex items-center gap-2 overflow-x-auto pb-1 scrollbar-hide">
          {NEWS_CATEGORIES.map((category) => (
            <button
              key={category.value}
              onClick={() => setActiveNewsCategory(category.value)}
              className={`shrink-0 rounded-full px-4 py-1.5 text-sm font-semibold transition-all ${
                activeNewsCategory === category.value
                  ? "bg-gray-900 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-100"
              }`}
              style={{ boxShadow: "0 1px 4px rgba(0,0,0,0.08)" }}
            >
              {category.label}
            </button>
          ))}
        </div>

        {isNewsLoading ? (
          <ArticleSkeletonGrid />
        ) : articles && articles.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {articles.map((article) => (
              <NewsFeedCard key={article.id} article={article} />
            ))}
          </div>
        ) : (
          <SectionEmptyState
            icon={<Newspaper className="mb-4 h-12 w-12 text-gray-200" />}
            title="No articles match this topic"
            detail="Try a broader search term or switch the news category."
          />
        )}
      </section>

      <section className="mt-10">
        <div className="mb-3 flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-geo-600" />
          <h2 className="text-base font-bold text-gray-900">Structured Event Intelligence</h2>
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">Published events only</span>
        </div>
        <p className="mb-4 max-w-3xl text-sm text-gray-500">
          These cards are the subset of news that passed extraction and confidence checks, with affected assets and
          event type attached.
        </p>
        <div className="mb-6 flex items-center gap-2 overflow-x-auto pb-1 scrollbar-hide">
          {EVENT_TYPES.map((type) => (
            <button
              key={type.value}
              onClick={() => setActiveType(type.value)}
              className={`shrink-0 rounded-full px-4 py-1.5 text-sm font-semibold transition-all ${
                activeType === type.value ? "bg-gray-900 text-white" : "bg-white text-gray-700 hover:bg-gray-100"
              }`}
              style={{ boxShadow: "0 1px 4px rgba(0,0,0,0.08)" }}
            >
              {type.label}
            </button>
          ))}
        </div>

        {isEventsLoading ? (
          <EventSkeletonGrid />
        ) : events && events.length > 0 ? (
          <MasonryGrid>
            {events.map((event) => (
              <EventPin key={event.id} event={event} onSave={setSaveTarget} />
            ))}
          </MasonryGrid>
        ) : (
          <SectionEmptyState
            icon={<Globe className="mb-4 h-12 w-12 text-gray-200" />}
            title="No structured events match this filter"
            detail="The raw news section above may still have articles for this topic."
          />
        )}
      </section>
    </div>
  );
}

function FeedStatCard({
  icon,
  title,
  value,
  detail,
}: {
  icon: ReactNode;
  title: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-[28px] border border-gray-200 bg-white px-4 py-4 shadow-sm">
      <div className="mb-3 inline-flex rounded-full bg-geo-50 p-2">{icon}</div>
      <p className="text-sm font-semibold text-gray-900">{title}</p>
      <p className="mt-1 text-lg font-bold text-gray-900">{value}</p>
      <p className="mt-1 text-xs text-gray-500">{detail}</p>
    </div>
  );
}

function ArticleSkeletonGrid() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-44 animate-pulse rounded-[28px] border border-gray-200 bg-gray-100" />
      ))}
    </div>
  );
}

function EventSkeletonGrid() {
  return (
    <MasonryGrid>
      {Array.from({ length: 18 }).map((_, i) => (
        <div key={i} className="skeleton mb-4 rounded-[var(--pin-radius)]" style={{ height: `${140 + (i % 4) * 40}px` }} />
      ))}
    </MasonryGrid>
  );
}

function SectionEmptyState({
  icon,
  title,
  detail,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[28px] border border-dashed border-gray-200 bg-white px-6 py-16 text-center">
      {icon}
      <h3 className="text-lg font-semibold text-gray-500">{title}</h3>
      <p className="mt-2 max-w-md text-sm text-gray-400">{detail}</p>
    </div>
  );
}
