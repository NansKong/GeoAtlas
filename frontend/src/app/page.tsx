"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ArrowRight, ArrowUpRight, Compass, Globe2, Newspaper, Radar, RefreshCw, Search, Sparkles } from "lucide-react";
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
  { value: "", label: "All events" }, { value: "conflict", label: "Conflict" },
  { value: "sanction", label: "Sanctions" }, { value: "trade_policy", label: "Trade" },
  { value: "energy_disruption", label: "Energy" }, { value: "election", label: "Elections" },
  { value: "regulation", label: "Regulation" }, { value: "economic_data", label: "Economy" },
];

export default function HomePage() {
  const [activeType, setActiveType] = useState("");
  const [topicQuery, setTopicQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [showAllEvents, setShowAllEvents] = useState(false);
  const [showAllNews, setShowAllNews] = useState(false);
  const [saveTarget, setSaveTarget] = useState<EventPinData | null>(null);

  const events = useQuery({
    queryKey: ["events", activeType, appliedQuery],
    queryFn: () => fetchEvents({ event_type: activeType || undefined, q: appliedQuery || undefined, status: "published", limit: 80 }),
  });
  const news = useQuery({
    queryKey: ["news-feed", appliedQuery],
    queryFn: () => fetchNews({ q: appliedQuery || undefined, limit: 24 }),
    staleTime: 60_000,
  });
  const predictions = useQuery({
    queryKey: ["prediction-feed-preview"],
    queryFn: () => fetchPredictions({ published_only: true, limit: 4 }),
    staleTime: 30_000,
  });

  const eventItems = Array.isArray(events.data) ? events.data : [];
  const newsItems = Array.isArray(news.data) ? news.data : [];
  const predictionItems = Array.isArray(predictions.data) ? predictions.data : [];

  return <div className="ga-shell">
    <SaveToBoardDialog open={saveTarget !== null} contentId={saveTarget?.id ?? ""} contentType="event" suggestedNote={saveTarget ? `${saveTarget.event_type.replace(/_/g, " ")} - ${saveTarget.title}` : ""} onClose={() => setSaveTarget(null)} />

    <section className="ga-hero">
      <span className="ga-eyebrow"><Radar size={15} /> THE GLOBAL SIGNAL DESK</span>
      <h1>Know what moves<br />the world.</h1>
      <p>Follow geopolitical developments, see where risk is building, and connect the story to markets in one clear view.</p>
      <div className="ga-hero-actions">
        <Link href="/map" className="ga-button ga-button-primary">Explore the live map <ArrowUpRight size={17} /></Link>
        <Link href="/news" className="ga-button ga-button-secondary">Browse latest news <ArrowRight size={17} /></Link>
      </div>
    </section>

    <div className="ga-metric-grid ga-stagger" aria-label="Current feed summary">
      <div className="ga-metric"><span>Published intelligence</span><strong>{events.isLoading || events.isError ? "—" : eventItems.length}</strong><p>{events.isError ? "Feed temporarily unavailable" : "Events shown in this view"}</p></div>
      <div className="ga-metric"><span>Source articles</span><strong>{news.isLoading || news.isError ? "—" : newsItems.length}</strong><p>{news.isError ? "Feed temporarily unavailable" : "Articles in the current feed"}</p></div>
      <div className="ga-metric"><span>Public predictions</span><strong>{predictions.isLoading || predictions.isError ? "—" : predictionItems.length}</strong><p>{predictions.isError ? "Feed temporarily unavailable" : predictionItems.length ? "Signals currently available" : "Waiting for verified signals"}</p></div>
    </div>

    <section className="ga-section" aria-labelledby="market-heading">
      <div className="ga-section-head"><div><span className="ga-eyebrow">01 / MARKET PULSE</span><h2 id="market-heading">The market, in context</h2><p>Explore live asset prices and the events connected to them.</p></div></div>
      <div className="ga-market-wrap"><MarketOverviewLayer /></div>
    </section>

    <section className="ga-section ga-overview-grid" aria-label="Saved assets and geographic activity">
      <div className="ga-overview-cell"><WatchlistPanel /></div>
      <div className="ga-overview-cell"><GeoHeatmapWidget /></div>
    </section>

    <section className="ga-section" aria-labelledby="events-heading">
      <div className="ga-section-head"><div><span className="ga-eyebrow">02 / STRUCTURED EVENTS</span><h2 id="events-heading">The stories behind the signals</h2><p>Published events with location, severity, and linked assets.</p></div><Link href="/map" className="ga-text-link">Explore the map <ArrowUpRight size={16} /></Link></div>
      <form className="ga-feed-search" onSubmit={(event) => { event.preventDefault(); setAppliedQuery(topicQuery.trim()); }} role="search">
        <Search size={19} aria-hidden="true" />
        <input aria-label="Search events and news" value={topicQuery} onChange={(event) => setTopicQuery(event.target.value)} placeholder="Search a country, company, topic or ticker" />
        {appliedQuery && <button type="button" className="ga-search-clear" onClick={() => { setTopicQuery(""); setAppliedQuery(""); }}>Clear</button>}
        <button type="submit" className="ga-search-submit">Search</button>
      </form>
      <div className="ga-chip-row ga-filter-row" role="group" aria-label="Event type">
        {EVENT_TYPES.map((type) => <button key={type.value} type="button" className={`ga-chip ${activeType === type.value ? "is-active" : ""}`} aria-pressed={activeType === type.value} onClick={() => { setActiveType(type.value); setShowAllEvents(false); }}>{type.label}</button>)}
      </div>
      {events.isLoading ? <div className="ga-loading-grid">{[0,1,2].map((item) => <div key={item} className="skeleton ga-panel" />)}</div>
      : events.isError ? <RetryCard title="Events are unavailable" detail="We couldn’t load this feed right now." onRetry={() => events.refetch()} />
      : eventItems.length ? <><MasonryGrid>{(showAllEvents ? eventItems : eventItems.slice(0, 9)).map((event) => <EventPin key={event.id} event={event} onSave={setSaveTarget} />)}</MasonryGrid>{eventItems.length > 9 && <button className="ga-show-more" onClick={() => setShowAllEvents((value) => !value)}>{showAllEvents ? "Show fewer events" : `Show all ${eventItems.length} events`} <ArrowRight size={16} /></button>}</>
      : <div className="ga-empty"><Globe2 size={25} /><h3>No events match this view</h3><p>Try another topic or event type. Raw articles may still be available below.</p></div>}
    </section>

    <section className="ga-section" aria-labelledby="news-heading">
      <div className="ga-section-head"><div><span className="ga-eyebrow">03 / SOURCE DESK</span><h2 id="news-heading">From the newsroom</h2><p>Original reporting, with source and publish time visible on every story.</p></div><Link href="/news" className="ga-text-link">All news <ArrowUpRight size={16} /></Link></div>
      {news.isLoading ? <div className="ga-loading-grid">{[0,1,2].map((item) => <div key={item} className="skeleton ga-panel" />)}</div>
      : news.isError ? <RetryCard title="News is unavailable" detail="We couldn’t load the latest articles." onRetry={() => news.refetch()} />
      : newsItems.length ? <><div className="ga-news-grid">{(showAllNews ? newsItems : newsItems.slice(0, 6)).map((article) => <NewsFeedCard key={article.id} article={article} />)}</div>{newsItems.length > 6 && <button className="ga-show-more" onClick={() => setShowAllNews((value) => !value)}>{showAllNews ? "Show fewer stories" : "More stories"} <ArrowRight size={16} /></button>}</>
      : <div className="ga-empty"><Newspaper size={25} /><h3>No articles found</h3><p>Try a broader search or browse the complete news feed.</p></div>}
    </section>

    <section className="ga-section" aria-labelledby="predictions-heading">
      <div className="ga-section-head"><div><span className="ga-eyebrow">04 / MODEL SIGNALS</span><h2 id="predictions-heading">Predictions, with context</h2><p>Only predictions that meet the public accuracy threshold appear here.</p></div><Link href="/predictions" className="ga-text-link">Prediction desk <ArrowUpRight size={16} /></Link></div>
      {predictions.isLoading ? <div className="skeleton ga-panel" style={{height:180}} /> : predictions.isError ? <RetryCard title="Predictions are unavailable" detail="Please try again shortly." onRetry={() => predictions.refetch()} /> : predictionItems.length ? <div className="ga-news-grid">{predictionItems.map((prediction) => <PredictionCard key={prediction.id} prediction={prediction} />)}</div> : <div className="ga-empty"><Sparkles size={26} /><h3>No verified predictions right now</h3><p>Explore the current events and market data while the model gathers enough outcomes to publish a signal.</p><Link href="/map" className="ga-text-link">Explore the map <ArrowRight size={16} /></Link></div>}
    </section>

    <section className="ga-section"><div className="ga-section-head"><div><span className="ga-eyebrow">05 / CROSS-ASSET VIEW</span><h2>Connections across markets</h2></div></div><CrossAssetCorrelation /></section>
  </div>;
}

function RetryCard({ title, detail, onRetry }: { title: string; detail: string; onRetry: () => void }) {
  return <div className="ga-empty"><Compass size={25} /><h3>{title}</h3><p>{detail}</p><button onClick={onRetry} className="ga-button ga-button-primary mt-5"><RefreshCw size={15} /> Try again</button></div>;
}
