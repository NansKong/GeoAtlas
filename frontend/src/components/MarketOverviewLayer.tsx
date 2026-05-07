"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, TrendingDown, Activity, Search, Clock, AlertTriangle } from "lucide-react";
import { MarketPanel } from "@/components/MarketPanel";
import { formatDistanceStrict, differenceInSeconds } from "date-fns";

interface SnapshotItem {
  id: string;
  ticker: string;
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
  const [activeTab, setActiveTab] = useState<"All" | "crypto" | "stock" | "forex" | "commodity" | "bond_etf">("All");
  const [searchTerm, setSearchTerm] = useState("");
  const [activeTicker, setActiveTicker] = useState<string>("NVDA");
  const [sortBy, setSortBy] = useState<SortOption>("Default");
  const [now, setNow] = useState(new Date());

  // Force re-render periodically to update the "seconds ago" timer
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const { data, isLoading, isError } = useQuery<SnapshotPayload>({
    queryKey: ["market-snapshot"],
    queryFn: async () => {
      const res = await fetch("http://localhost:8000/api/v1/market/snapshot");
      if (!res.ok) throw new Error("Failed to fetch snapshot");
      const d = await res.json();
      return d as SnapshotPayload;
    },
    refetchInterval: () =>
      typeof document !== 'undefined' && document.visibilityState !== 'visible' ? 15000 : 5000,
  });

  const snapshotData: SnapshotItem[] = Array.isArray(data?.snapshot) ? data!.snapshot : [];
  
  const filteredData = snapshotData.filter((item) => {
    if (activeTab !== "All" && item.asset_type !== activeTab) return false;
    if (searchTerm && !item.ticker.includes(searchTerm.toUpperCase())) return false;
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
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="flex flex-wrap gap-1.5">
          {([
            { key: "All", label: "All" },
            { key: "crypto", label: "Crypto" },
            { key: "stock", label: "Stocks" },
            { key: "forex", label: "Forex" },
            { key: "commodity", label: "Commodities" },
            { key: "bond_etf", label: "Bonds/ETFs" },
          ] as const).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-3.5 py-1.5 rounded-full text-sm font-semibold transition-colors ${
                activeTab === tab.key
                  ? "bg-gray-900 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-50 border border-gray-200"
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
            className="pl-3 pr-8 py-2 rounded-full border border-gray-300 text-sm font-semibold text-gray-700 focus:outline-none focus:ring-2 focus:ring-geo-500 bg-white"
          >
            <option value="Default">Sort: A-Z</option>
            <option value="Event-Driven Movers">🔥 Event-Driven Movers</option>
            <option value="Highest Impact">⭐ Highest Impact</option>
            <option value="Most Volatile">⚡ Most Volatile</option>
            <option value="Top Gainers">📈 Top Gainers</option>
            <option value="Top Losers">📉 Top Losers</option>
          </select>
          
          <div className="relative flex-1 md:flex-initial">
            <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search assets..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9 pr-4 py-2 rounded-full border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-geo-500 w-full font-medium"
            />
          </div>
        </div>
      </div>

      <div className="rounded-[1.4rem] bg-white border border-gray-200 p-5 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
            <Activity className="w-5 h-5 text-geo-600" />
            Market Snapshot
          </h2>
          
          <div className="flex items-center gap-2">
            {data?.source_status && (
                <div className="hidden md:flex gap-2 mr-2 text-[10px] uppercase font-bold text-gray-400 tracking-wider">
                  <span className={data.source_status.polygon === "live" ? "text-teal-600" : "text-rose-600"}>POLYGON {data.source_status.polygon}</span>
                  <span className={data.source_status.binance === "live" ? "text-teal-600" : "text-rose-600"}>BINANCE {data.source_status.binance}</span>
                </div>
            )}
            
            {lastUpdatedRaw && (
              <div className={`flex items-center gap-1.5 text-xs font-semibold ${stalenessColor} bg-gray-50 px-2 py-1.5 rounded-lg border border-gray-100 shadow-sm`}>
                <StalenessIcon className="w-3.5 h-3.5" />
                <span>
                 {stalenessDocs < 2 ? "Updated just now" : `Updated ${formatDistanceStrict(lastUpdatedRaw, now, { addSuffix: true })}`}
                </span>
              </div>
            )}
          </div>
        </div>
        
        {isLoading ? (
          <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {[...Array(10)].map((_, i) => (
              <div key={i} className="h-24 rounded-xl bg-gray-100 animate-pulse" />
            ))}
          </div>
        ) : isError ? (
          <div className="text-sm text-red-600 p-4 border border-red-200 bg-red-50 rounded-xl">Failed to load market snapshot connection. Is the backend running?</div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-3 max-h-[400px] overflow-y-auto pr-2 pb-2">
            {sortedData.map((item) => {
              const isUp = item.change >= 0;
              const hasRisk = item.risk === "high";
              const tag = item.tag;
              const hasIntel = !!tag && (item.impact_score || 0) > 0;
              
              return (
                <div
                  key={item.ticker}
                  onClick={() => setActiveTicker(item.ticker)}
                  className={`relative p-3 rounded-xl border transition-all cursor-pointer hover:shadow-md group ${
                    activeTicker === item.ticker ? "border-geo-500 bg-geo-50/40 ring-1 ring-geo-200" : "border-gray-100 bg-white hover:border-gray-300"
                  }`}
                >
                  <div className="flex justify-between items-start mb-1 h-6">
                    <span className="font-bold text-gray-900 tracking-tight">{item.ticker}</span>
                    {hasIntel && (
                      <span className={`text-[11px] h-5 px-1.5 rounded-md flex items-center justify-center font-bold shadow-sm ${
                        hasRisk ? "bg-rose-100 text-rose-700 border border-rose-200" : "bg-emerald-100 text-emerald-700 border border-emerald-200"
                      }`}>
                        {tag.charAt(0)} {(item.impact_score || 0).toFixed(2)}
                      </span>
                    )}
                  </div>
                  
                  <div className="text-lg font-bold text-gray-800 tabular-nums">
                    ${item.price < 1 ? item.price.toFixed(4) : item.price.toFixed(2)}
                  </div>
                  
                  <div className={`mt-0.5 flex items-center gap-0.5 text-xs font-bold tabular-nums ${isUp ? "text-teal-600" : "text-rose-600"}`}>
                    {isUp ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                    {isUp ? "+" : ""}{item.change.toFixed(2)}%
                  </div>
                  
                  {hasIntel && (
                    <div className="absolute hidden group-hover:block z-20 bottom-full left-1/2 -translate-x-1/2 mb-2 w-max max-w-xs bg-gray-900 text-white text-xs rounded-xl px-3 py-2.5 shadow-2xl pointer-events-none border border-gray-700">
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
                <div className="col-span-full py-10 flex text-center justify-center text-sm font-medium text-gray-400">
                    No tracked assets map to the current view or search query.
                </div>
            )}
          </div>
        )}
      </div>

      <MarketPanel customTicker={activeTicker} />
    </div>
  );
}
