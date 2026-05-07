"use client";

import { formatDistanceToNow } from "date-fns";
import { ExternalLink, Newspaper } from "lucide-react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { NewsArticle } from "@/lib/api";

const CATEGORY_STYLES: Record<string, string> = {
  conflict: "bg-rose-100 text-rose-800 border-rose-200",
  sanction: "bg-amber-100 text-amber-800 border-amber-200",
  trade_policy: "bg-sky-100 text-sky-800 border-sky-200",
  economic_data: "bg-emerald-100 text-emerald-800 border-emerald-200",
  energy_disruption: "bg-orange-100 text-orange-800 border-orange-200",
  election: "bg-violet-100 text-violet-800 border-violet-200",
  regulation: "bg-lime-100 text-lime-800 border-lime-200",
  markets: "bg-slate-100 text-slate-700 border-slate-200",
  general: "bg-gray-100 text-gray-700 border-gray-200",
};

function formatCategoryLabel(category: string) {
  return category.replace(/_/g, " ");
}

interface NewsFeedCardProps {
  article: NewsArticle;
}

export function NewsFeedCard({ article }: NewsFeedCardProps) {
  const categoryTone = CATEGORY_STYLES[article.category] ?? CATEGORY_STYLES.general;
  const timeAgo = article.published_at
    ? formatDistanceToNow(new Date(article.published_at), { addSuffix: true })
    : null;

  return (
    <Card className="border-gray-200 bg-white/95 shadow-sm">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`inline-flex rounded-full border px-2 py-1 text-[11px] font-semibold ${categoryTone}`}>
                {formatCategoryLabel(article.category)}
              </span>
              {article.matched_event_type && article.matched_event_type !== article.category && (
                <span className="inline-flex rounded-full border border-gray-200 bg-gray-50 px-2 py-1 text-[11px] font-medium text-gray-600">
                  {formatCategoryLabel(article.matched_event_type)}
                </span>
              )}
            </div>
            <h3 className="text-sm font-semibold leading-snug text-gray-900">{article.title}</h3>
          </div>
          <a
            href={article.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1 rounded-full border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            Open
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {article.snippet && <p className="text-sm leading-6 text-gray-600">{article.snippet}</p>}
        <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
          <span className="inline-flex items-center gap-1">
            <Newspaper className="h-3.5 w-3.5" />
            {article.source}
          </span>
          {timeAgo && <span>{timeAgo}</span>}
        </div>
      </CardContent>
    </Card>
  );
}
