"use client";

import { useQuery } from "@tanstack/react-query";
import { Newspaper, Search } from "lucide-react";
import { useState } from "react";

import { NewsFeedCard } from "@/components/NewsFeedCard";
import { fetchNews } from "@/lib/api";

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

export default function NewsPage() {
  const [topicQuery, setTopicQuery] = useState("");
  const [appliedTopicQuery, setAppliedTopicQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState("");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["raw-news-feed", appliedTopicQuery, activeCategory],
    queryFn: () =>
      fetchNews({
        q: appliedTopicQuery || undefined,
        category: activeCategory || undefined,
        limit: 120,
      }),
    staleTime: 60_000,
  });

  return (
    <div className="mx-auto max-w-screen-xl px-4 py-6">
      <div className="mb-5 flex items-center gap-2">
        <Newspaper className="h-5 w-5 text-geo-600" />
        <h1 className="text-lg font-bold text-gray-900">Raw News Feed</h1>
      </div>

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            value={topicQuery}
            onChange={(e) => setTopicQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") setAppliedTopicQuery(topicQuery.trim());
            }}
            placeholder="Search the raw feed"
            className="h-10 w-full rounded-full border border-gray-300 bg-white pl-9 pr-4 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-geo-300"
          />
        </div>
        <button
          onClick={() => setAppliedTopicQuery(topicQuery.trim())}
          className="h-10 rounded-full bg-gray-900 px-4 text-sm font-semibold text-white transition-colors hover:bg-gray-800"
        >
          Apply
        </button>
      </div>

      <div className="mb-5 flex items-center gap-2 overflow-x-auto pb-1 scrollbar-hide">
        {NEWS_CATEGORIES.map((category) => (
          <button
            key={category.value}
            onClick={() => setActiveCategory(category.value)}
            className={`shrink-0 rounded-full px-4 py-1.5 text-sm font-semibold transition-all ${
              activeCategory === category.value ? "bg-gray-900 text-white" : "bg-white text-gray-700 hover:bg-gray-100"
            }`}
            style={{ boxShadow: "0 1px 4px rgba(0,0,0,0.08)" }}
          >
            {category.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {Array.from({ length: 8 }).map((_, idx) => (
            <div key={idx} className="h-44 animate-pulse rounded-[28px] border border-gray-200 bg-gray-100" />
          ))}
        </div>
      ) : isError ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Unable to fetch raw news articles.
        </div>
      ) : !data || data.length === 0 ? (
        <div className="rounded-2xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          No raw articles match this filter.
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.map((article) => (
            <NewsFeedCard key={article.id} article={article} />
          ))}
        </div>
      )}
    </div>
  );
}
