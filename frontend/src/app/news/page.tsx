"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Clock3, Newspaper, RefreshCw, Search } from "lucide-react";
import { NewsFeedCard } from "@/components/NewsFeedCard";
import { fetchNews } from "@/lib/api";
import { safeDistanceToNow } from "@/lib/dateUtils";

const categories = [
  { value: "", label: "All stories" }, { value: "markets", label: "Markets" },
  { value: "economic_data", label: "Economy" }, { value: "trade_policy", label: "Trade" },
  { value: "regulation", label: "Regulation" }, { value: "energy_disruption", label: "Energy" },
  { value: "conflict", label: "Conflict" }, { value: "election", label: "Elections" },
  { value: "sanction", label: "Sanctions" }, { value: "general", label: "General" },
];

export default function NewsPage() {
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const news = useQuery({ queryKey: ["raw-news-feed", query, category], queryFn: () => fetchNews({ q: query || undefined, category: category || undefined, limit: 120 }), staleTime: 60_000 });
  const articles = useMemo(() => {
    const seen = new Set<string>();
    return (news.data ?? []).filter((article) => {
      const key = article.url?.trim().toLowerCase() || article.id;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [news.data]);
  const newest = articles.reduce<string | undefined>((latest, article) => {
    const published = article.published_at;
    return published && (!latest || published > latest) ? published : latest;
  }, undefined);

  return <div className="ga-shell">
    <section className="ga-hero">
      <span className="ga-eyebrow"><Newspaper size={15} /> SOURCE DESK</span>
      <h1>Read the source.<br />See the bigger picture.</h1>
      <p>Browse original reporting, filter by subject, and trace the headlines that shape GeoAtlas intelligence.</p>
      <div className="ga-hero-actions"><Link href="/map" className="ga-button ga-button-secondary">Explore geographic activity <ArrowRight size={16} /></Link></div>
    </section>

    <section className="ga-section" aria-labelledby="stories-heading">
      <div className="ga-section-head"><div><span className="ga-eyebrow">LATEST COVERAGE</span><h2 id="stories-heading">From trusted sources</h2><p>{news.isLoading ? "Loading stories…" : `${articles.length} distinct stories shown${newest ? ` · newest ${safeDistanceToNow(newest)}` : ""}`}</p></div></div>
      <form className="ga-feed-search" onSubmit={(event) => { event.preventDefault(); setQuery(draftQuery.trim()); }} role="search"><Search size={18} /><input aria-label="Search news" value={draftQuery} onChange={(event) => setDraftQuery(event.target.value)} placeholder="Search a topic, country, source, or asset" />{query && <button type="button" className="ga-search-clear" onClick={() => { setDraftQuery(""); setQuery(""); }}>Clear</button>}<button type="submit" className="ga-search-submit">Search</button></form>
      <div className="ga-chip-row ga-filter-row" role="group" aria-label="News category">{categories.map((item) => <button key={item.value} type="button" className={`ga-chip ${category === item.value ? "is-active" : ""}`} aria-pressed={category === item.value} onClick={() => setCategory(item.value)}>{item.label}</button>)}</div>
      {newest && Date.now() - new Date(newest).getTime() > 24 * 60 * 60 * 1000 && <div className="ga-stale-note"><Clock3 size={18} /><span>The latest available article is {safeDistanceToNow(newest)}. Live ingestion may be delayed; timestamps on each story show when it was published.</span></div>}
      {news.isLoading ? <div className="ga-loading-grid">{[0,1,2].map((index) => <div key={index} className="skeleton ga-panel" />)}</div>
      : news.isError ? <div className="ga-empty"><h3>News is unavailable</h3><p>We couldn’t load the source feed right now.</p><button className="ga-button ga-button-primary mt-5" onClick={() => news.refetch()}><RefreshCw size={15} /> Try again</button></div>
      : articles.length === 0 ? <div className="ga-empty"><h3>No stories match this search</h3><p>Try another topic or category.</p></div>
      : <div className="ga-news-grid">{articles.map((article) => <NewsFeedCard key={article.id} article={article} />)}</div>}
    </section>
  </div>;
}
