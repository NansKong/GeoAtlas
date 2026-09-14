"use client";

import { useState, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Activity,
  Search,
  Clock,
  AlertTriangle,
  Loader2,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { MarketPanel } from "@/components/MarketPanel";
import { formatDistanceStrict, differenceInSeconds } from "date-fns";

interface SnapshotItem {
  id: string;
  ticker: string;
  name?: string;
  asset_type: string;
  price: number;
  change: number;
  source: string;
  as_of: string;
  tag?: string;
  risk?: string;
  impact_score?: number;
}

interface SnapshotPayload {
  snapshot: SnapshotItem[];
  last_updated: string | null;
  source_status: { binance: string; polygon: string };
}

type SortOption =
  | "Default"
  | "Event-Driven Movers"
  | "Highest Impact"
  | "Most Volatile"
  | "Top Gainers"
  | "Top Losers";

export function MarketOverviewLayer() {
  const [activeTab, setActiveTab] = useState<
    "All" | "crypto" | "stock" | "forex" | "commodity" | "bond_etf"
  >("All");
  const [searchTerm, setSearchTerm] = useState("");
  const [activeTicker, setActiveTicker] = useState<string>("NVDA");
  const [sortBy, setSortBy] = useState<SortOption>("Default");
  const [now, setNow] = useState(new Date());

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const [isSearchingLive, setIsSearchingLive] = useState(false);

  // Force re-render periodically to update the "seconds ago" timer
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const handleScroll = (direction: "left" | "right") => {
    if (scrollContainerRef.current) {
      const scrollAmount = direction === "left" ? -400 : 400;
      scrollContainerRef.current.scrollBy({ left: scrollAmount, behavior: "smooth" });
    }
  };

  const handleLiveSymbolSearch = async (queryStr: string) => {
    const cleanStr = queryStr.trim();
    if (!cleanStr) return;
    setIsSearchingLive(true);
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
      const res = await fetch(
        `${baseUrl}/market/quote/${encodeURIComponent(cleanStr)}?refresh=true`
      );
      if (res.ok) {
        const data = await res.json();
        if (data && data.ticker) {
          setActiveTicker(data.ticker);
        }
        await queryClient.invalidateQueries({ queryKey: ["market-snapshot"] });
      } else {
        alert(`Could not fetch live market data for "${cleanStr}". Please verify the symbol or company name.`);
      }
    } catch (err) {
      console.error("Live symbol search error:", err);
    } finally {
      setIsSearchingLive(false);
    }
  };

  const { data, isLoading } = useQuery<SnapshotPayload>({
    queryKey: ["market-snapshot"],
    queryFn: async () => {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
      const res = await fetch(`${baseUrl}/market/snapshot`);
      if (!res.ok) throw new Error("Failed to fetch snapshot");
      const d = await res.json();
      return d as SnapshotPayload;
    },
    refetchInterval: () =>
      typeof document !== "undefined" && document.visibilityState !== "visible" ? 15000 : 5000,
  });

  const snapshotData: SnapshotItem[] = Array.isArray(data?.snapshot) ? data!.snapshot : [];

  const COMMODITY_TICKERS = new Set([
    "GLD", "SLV", "USO", "UNG", "PDBC", "CPER", "XAUUSD", "XAGUSD",
    "GOLD", "SILVER", "CL=F", "GC=F", "SI=F", "NG=F", "HG=F"
  ]);

  const term = searchTerm.trim().toLowerCase();
  const filteredData = snapshotData.filter((item) => {
    if (activeTab !== "All") {
      const typeLower = (item.asset_type || "").toLowerCase();
      const tickerUpper = (item.ticker || "").toUpperCase();

      if (activeTab === "commodity") {
        const isCommodity = typeLower === "commodity" || COMMODITY_TICKERS.has(tickerUpper);
        if (!isCommodity) return false;
      } else if (activeTab === "bond_etf") {
        const isEtf = typeLower === "etf" || typeLower === "bond_etf" || typeLower === "bond";
        if (!isEtf) return false;
      } else if (activeTab === "stock") {
        const isStock = typeLower === "stock" || typeLower === "equity";
        if (!isStock) return false;
      } else {
        if (typeLower !== activeTab.toLowerCase()) return false;
      }
    }

    if (term) {
      const matchesTicker = item.ticker.toLowerCase().includes(term);
      const matchesName = item.name ? item.name.toLowerCase().includes(term) : false;
      if (!matchesTicker && !matchesName) return false;
    }
    return true;
  });

  const sortedData = [...filteredData].sort((a, b) => {
    switch (sortBy) {
      case "Top Gainers":
        return b.change - a.change;
      case "Top Losers":
        return a.change - b.change;
      case "Most Volatile":
        return Math.abs(b.change) - Math.abs(a.change);
      case "Highest Impact":
        return (b.impact_score || 0) - (a.impact_score || 0);
      case "Event-Driven Movers": {
        const scoreA = (a.impact_score || 0) * Math.abs(a.change);
        const scoreB = (b.impact_score || 0) * Math.abs(b.change);
        return scoreB - scoreA;
      }
      default:
        return a.ticker.localeCompare(b.ticker);
    }
  });

  // Staleness calculation
  const lastUpdatedRaw = data?.last_updated ? new Date(data.last_updated) : null;
  const stalenessDocs = lastUpdatedRaw ? differenceInSeconds(now, lastUpdatedRaw) : 0;

  let stalenessColor = "text-gray-500";
  let StalenessIcon = Clock;
  if (stalenessDocs >= 30) {
    stalenessColor = "text-red-700";
    StalenessIcon = AlertTriangle;
  } else if (stalenessDocs >= 15) {
    stalenessColor = "text-amber-600";
    StalenessIcon = AlertTriangle;
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Category Tabs & Search Bar */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="flex flex-wrap gap-1.5">
          {([
            { key: "All", label: "All Assets" },
            { key: "stock", label: "Stocks" },
            { key: "crypto", label: "Crypto" },
            { key: "commodity", label: "Commodities" },
            { key: "forex", label: "Forex" },
            { key: "bond_etf", label: "Bonds/ETFs" },
          ] as const).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-1.5 rounded-full text-xs font-bold transition-all ${
                activeTab === tab.key
                  ? "bg-gray-900 text-white shadow-sm"
                  : "bg-white text-gray-700 hover:bg-gray-100 border border-gray-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 w-full md:w-auto">
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortOption)}
            className="pl-3 pr-8 py-2 rounded-full border border-gray-300 text-xs font-bold text-gray-700 focus:outline-none focus:ring-2 focus:ring-geo-500 bg-white shadow-sm"
          >
            <option value="Default">Sort: A-Z</option>
            <option value="Event-Driven Movers">🔥 Event-Driven Movers</option>
            <option value="Highest Impact">⭐ Highest Impact</option>
            <option value="Most Volatile">⚡ Most Volatile</option>
            <option value="Top Gainers">📈 Top Gainers</option>
            <option value="Top Losers">📉 Top Losers</option>
          </select>

          <div className="relative flex-1 md:w-72">
            <Search className="w-4 h-4 text-gray-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search Amazon, Silver, TSLA..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && searchTerm.trim()) {
                  handleLiveSymbolSearch(searchTerm);
                }
              }}
              className="pl-9 pr-4 py-2 rounded-full border border-gray-300 text-xs focus:outline-none focus:ring-2 focus:ring-geo-500 w-full font-medium shadow-sm bg-white"
            />
          </div>
        </div>
      </div>

      {/* Market Snapshot Container */}
      <div className="rounded-[1.4rem] bg-white border border-gray-200 p-5 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
            <Activity className="w-5 h-5 text-geo-600" />
            Market Snapshot
          </h2>

          <div className="flex items-center gap-2">
            {data?.source_status && (
              <div className="hidden md:flex gap-2 mr-2 text-[10px] uppercase font-bold text-gray-400 tracking-wider">
                <span className={data.source_status.polygon === "live" ? "text-teal-600" : "text-rose-600"}>
                  POLYGON {data.source_status.polygon}
                </span>
                <span className={data.source_status.binance === "live" ? "text-teal-600" : "text-rose-600"}>
                  BINANCE {data.source_status.binance}
                </span>
              </div>
            )}

            <div className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1 rounded-full bg-gray-100 border border-gray-200">
              <StalenessIcon className={`w-3.5 h-3.5 ${stalenessColor}`} />
              <span className={stalenessColor}>
                {lastUpdatedRaw ? `Updated ${formatDistanceStrict(lastUpdatedRaw, now)} ago` : "Connecting..."}
              </span>
            </div>
          </div>
        </div>

        {isLoading ? (
          <div className="py-12 flex justify-center text-sm font-medium text-gray-400">Loading live snapshot...</div>
        ) : (
          <div className="relative group/slider">
            {/* Left Scroll Button */}
            <button
              onClick={() => handleScroll("left")}
              className="absolute -left-3 top-1/2 -translate-y-1/2 z-20 w-9 h-9 rounded-full bg-white shadow-md border border-gray-200 flex items-center justify-center text-gray-700 hover:bg-geo-50 hover:text-geo-600 transition-all opacity-0 group-hover/slider:opacity-100 cursor-pointer"
              aria-label="Scroll Left"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>

            {/* Horizontal Column Scroll Track */}
            <div
              ref={scrollContainerRef}
              className="flex overflow-x-auto gap-3 py-2 px-1 scrollbar-none snap-x snap-mandatory scroll-smooth"
              style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}
            >
              {sortedData.map((item) => {
                const isUp = item.change > 0;
                const isZero = Math.abs(item.change) < 0.0001;
                const hasIntel = !!item.tag;
                const tag = item.tag || "";
                const fullName = item.name || item.ticker;

                return (
                  <div
                    key={item.id}
                    onClick={() => setActiveTicker(item.ticker)}
                    className={`min-w-[210px] w-[210px] shrink-0 snap-start relative group cursor-pointer p-3.5 rounded-2xl border transition-all duration-200 hover:shadow-md ${
                      activeTicker === item.ticker
                        ? "border-geo-500 bg-geo-50/40 ring-2 ring-geo-500/20"
                        : "border-gray-200 bg-white hover:border-gray-300"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="font-extrabold text-gray-900 text-sm tracking-tight">{item.ticker}</span>
                      {hasIntel && (
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-black tracking-wide uppercase bg-emerald-100 text-emerald-800">
                          {tag.slice(0, 8)}
                        </span>
                      )}
                    </div>

                    <div className="text-[11px] font-semibold text-gray-400 truncate mb-2" title={fullName}>
                      {fullName}
                    </div>

                    <div className="text-base font-extrabold text-gray-900 tracking-tight">
                      ${item.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>

                    <div className={`mt-0.5 flex items-center gap-0.5 text-xs font-bold tabular-nums ${isZero ? "text-gray-400" : isUp ? "text-teal-600" : "text-rose-600"}`}>
                      {isZero ? <Minus className="w-3.5 h-3.5" /> : isUp ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                      {isZero ? "0.00%" : `${isUp ? "+" : ""}${item.change.toFixed(2)}%`}
                    </div>

                    {/* Intelligence Tooltip Hover */}
                    {hasIntel && (
                      <div className="absolute hidden group-hover:block z-30 bottom-full left-1/2 -translate-x-1/2 mb-2 w-max max-w-xs bg-gray-900 text-white text-xs rounded-xl px-3 py-2.5 shadow-2xl pointer-events-none border border-gray-700">
                        <div className="font-bold mb-1 text-gray-300 uppercase tracking-widest text-[10px]">{item.ticker} INTELLIGENCE</div>
                        <div className="text-gray-100 font-medium leading-tight">{tag}</div>
                        {typeof item.impact_score === "number" && (
                          <div className="mt-1.5 text-geo-400 font-bold text-[10px] uppercase">
                            COMBINED IMPACT: {item.impact_score.toFixed(3)}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}

              {sortedData.length === 0 && (
                <div className="w-full py-8 flex flex-col items-center justify-center text-center">
                  <p className="text-sm font-medium text-gray-500 mb-3">
                    No active assets matching &quot;{searchTerm}&quot;.
                  </p>
                  {searchTerm.trim().length >= 1 && (
                    <button
                      onClick={() => handleLiveSymbolSearch(searchTerm)}
                      disabled={isSearchingLive}
                      className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-full shadow-sm transition-all disabled:opacity-50 cursor-pointer"
                    >
                      {isSearchingLive ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Search className="w-4 h-4" />
                      )}
                      Fetch Live Market Data for &quot;{searchTerm}&quot;
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* Right Scroll Button */}
            <button
              onClick={() => handleScroll("right")}
              className="absolute -right-3 top-1/2 -translate-y-1/2 z-20 w-9 h-9 rounded-full bg-white shadow-md border border-gray-200 flex items-center justify-center text-gray-700 hover:bg-geo-50 hover:text-geo-600 transition-all opacity-0 group-hover/slider:opacity-100 cursor-pointer"
              aria-label="Scroll Right"
            >
              <ChevronRight className="w-5 h-5" />
            </button>
          </div>
        )}
      </div>

      <MarketPanel customTicker={activeTicker} />
    </div>
  );
}
