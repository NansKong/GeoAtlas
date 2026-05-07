"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownRight,
  ArrowUpRight,
  Flame,
  Globe2,
  Layers,
  Link2,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import {
  fetchEvents,
  fetchMarketQuote,
  fetchMarketSnapshot,
  type EventListItem,
  type MarketSnapshotItem,
} from "@/lib/api";

const BENCHMARK_TICKERS = [
  { ticker: "SPY", label: "S&P 500", category: "equity" },
  { ticker: "QQQ", label: "Nasdaq 100", category: "equity" },
  { ticker: "AAPL", label: "Apple", category: "equity" },
  { ticker: "TLT", label: "20Y Treasury", category: "bond" },
  { ticker: "GLD", label: "Gold", category: "commodity" },
  { ticker: "DXY", label: "US Dollar", category: "forex" },
  { ticker: "BTC", label: "Bitcoin", category: "crypto" },
  { ticker: "ETH", label: "Ethereum", category: "crypto" },
] as const;

type AssetClass = "equity" | "bond" | "commodity" | "forex" | "crypto";

const CLASS_COLORS: Record<AssetClass, { bg: string; border: string; text: string; dot: string }> = {
  equity: { bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-700", dot: "bg-blue-400" },
  bond: { bg: "bg-amber-50", border: "border-amber-200", text: "text-amber-700", dot: "bg-amber-400" },
  commodity: { bg: "bg-yellow-50", border: "border-yellow-200", text: "text-yellow-700", dot: "bg-yellow-500" },
  forex: { bg: "bg-purple-50", border: "border-purple-200", text: "text-purple-700", dot: "bg-purple-400" },
  crypto: { bg: "bg-orange-50", border: "border-orange-200", text: "text-orange-700", dot: "bg-orange-400" },
};

function findCorrelations(events: EventListItem[] | undefined) {
  if (!events || events.length === 0) return [];

  const assetMap = new Map<string, Set<string>>();
  for (const event of events) {
    if (!event.affected_assets || event.affected_assets.length < 2) continue;
    const tickers = event.affected_assets.map((a) => a.ticker);
    const classes = new Set<string>();
    for (const t of tickers) {
      const bench = BENCHMARK_TICKERS.find((b) => b.ticker === t);
      if (bench) classes.add(bench.category);
    }
    if (classes.size >= 2) {
      const key = Array.from(classes).sort().join("↔");
      if (!assetMap.has(key)) assetMap.set(key, new Set());
      assetMap.get(key)!.add(event.title);
    }
  }

  return Array.from(assetMap.entries())
    .map(([pair, evts]) => ({ pair, eventCount: evts.size, events: Array.from(evts).slice(0, 3) }))
    .sort((a, b) => b.eventCount - a.eventCount)
    .slice(0, 5);
}

/**
 * Fetch individual quotes for benchmark tickers that are missing from the snapshot.
 */
async function fetchMissingQuotes(missingTickers: string[]): Promise<Map<string, { price: number; change: number }>> {
  const results = new Map<string, { price: number; change: number }>();
  const fetches = missingTickers.map(async (ticker) => {
    try {
      const quote = await fetchMarketQuote(ticker);
      // The quote API returns price but not change %; set change to 0 as fallback
      results.set(ticker, { price: quote.price, change: 0 });
    } catch {
      // Ticker not available, skip
    }
  });
  await Promise.allSettled(fetches);
  return results;
}

export function CrossAssetCorrelation() {
  const { data: snapshot } = useQuery({
    queryKey: ["market-snapshot-crossasset"],
    queryFn: fetchMarketSnapshot,
    staleTime: 10_000,
  });

  const { data: events } = useQuery({
    queryKey: ["events-crossasset"],
    queryFn: () => fetchEvents({ status: "published", limit: 60 }),
    staleTime: 30_000,
  });

  const snapshotMap = useMemo(() => {
    const map = new Map<string, MarketSnapshotItem>();
    if (snapshot?.snapshot) {
      for (const item of snapshot.snapshot) map.set(item.ticker, item);
    }
    return map;
  }, [snapshot]);

  // Find tickers missing from the snapshot and fetch individual quotes
  const missingTickers = useMemo(() => {
    return BENCHMARK_TICKERS
      .filter((b) => !snapshotMap.has(b.ticker))
      .map((b) => b.ticker);
  }, [snapshotMap]);

  const { data: fallbackQuotes } = useQuery({
    queryKey: ["benchmark-fallback", missingTickers.join(",")],
    queryFn: () => fetchMissingQuotes(missingTickers),
    enabled: missingTickers.length > 0,
    staleTime: 30_000,
  });

  const correlations = useMemo(() => findCorrelations(events), [events]);

  const benchmarks = BENCHMARK_TICKERS.map((b) => {
    const snapshotData = snapshotMap.get(b.ticker);
    const fallback = fallbackQuotes?.get(b.ticker);
    return {
      ...b,
      price: snapshotData?.price ?? fallback?.price ?? null,
      change: snapshotData?.change ?? fallback?.change ?? null,
      tag: snapshotData?.tag,
      impactScore: snapshotData?.impact_score,
    };
  });

  return (
    <section className="mt-6">
      <div className="mb-4 flex items-center gap-2">
        <Layers className="h-5 w-5 text-geo-600" />
        <h2 className="text-base font-bold text-gray-900">Cross-Asset Intelligence</h2>
        <span className="rounded-full bg-geo-50 px-2 py-0.5 text-xs font-medium text-geo-700">TradFi + Crypto</span>
      </div>

      {/* Benchmark Strip */}
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
        {benchmarks.map((b) => {
          const cls = CLASS_COLORS[b.category as AssetClass];
          const isUp = (b.change ?? 0) >= 0;
          const hasPrice = b.price !== null;
          return (
            <div
              key={b.ticker}
              className={`rounded-2xl border p-3 transition-shadow hover:shadow-md ${cls.border} ${cls.bg}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className={`h-2 w-2 rounded-full ${cls.dot}`} />
                  <span className="text-xs font-bold text-gray-800">{b.ticker}</span>
                </div>
                {b.tag && b.impactScore && b.impactScore > 0.1 && (
                  <Flame className="h-3 w-3 text-orange-500" />
                )}
              </div>
              <p className="mt-1 text-sm font-bold tabular-nums text-gray-900">
                {hasPrice
                  ? b.price! < 1
                    ? `$${b.price!.toFixed(4)}`
                    : `$${b.price!.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                  : "—"}
              </p>
              <div className={`mt-0.5 flex items-center gap-0.5 text-[11px] font-bold tabular-nums ${
                !hasPrice ? "text-gray-400" : isUp ? "text-emerald-600" : "text-rose-600"
              }`}>
                {hasPrice ? (
                  <>
                    {isUp ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                    {b.change !== null ? `${isUp ? "+" : ""}${b.change.toFixed(2)}%` : "—"}
                  </>
                ) : (
                  <span className="text-gray-400">awaiting data</span>
                )}
              </div>
              <p className="mt-1 truncate text-[10px] text-gray-500">{b.label}</p>
            </div>
          );
        })}
      </div>

      {/* Cross-Asset Correlations */}
      {correlations.length > 0 && (
        <div className="rounded-[24px] border border-gray-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Link2 className="h-4 w-4 text-geo-600" />
            <h3 className="text-sm font-semibold text-gray-900">Event-Driven Cross-Asset Links</h3>
          </div>
          <p className="mb-3 text-xs text-gray-500">
            Events simultaneously affecting multiple asset classes signal cross-market contagion risk.
          </p>
          <div className="space-y-2">
            {correlations.map((c) => {
              const classes = c.pair.split("↔");
              return (
                <div key={c.pair} className="rounded-xl border border-gray-100 bg-gray-50/60 p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {classes.map((clsName) => {
                        const colors = CLASS_COLORS[clsName as AssetClass] ?? CLASS_COLORS.equity;
                        return (
                          <span key={clsName} className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${colors.border} ${colors.bg} ${colors.text}`}>
                            {clsName}
                          </span>
                        );
                      })}
                      <ArrowDownRight className="h-3 w-3 text-gray-300" />
                      <ArrowUpRight className="h-3 w-3 text-gray-300" />
                    </div>
                    <span className="rounded-full bg-geo-100 px-2 py-0.5 text-[10px] font-bold text-geo-700">
                      {c.eventCount} shared event{c.eventCount > 1 ? "s" : ""}
                    </span>
                  </div>
                  <div className="mt-2 space-y-0.5">
                    {c.events.map((evt, i) => (
                      <p key={i} className="truncate text-xs text-gray-600">• {evt}</p>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {correlations.length === 0 && (
        <div className="rounded-[24px] border border-dashed border-gray-200 bg-white px-4 py-8 text-center">
          <Globe2 className="mx-auto mb-2 h-8 w-8 text-gray-200" />
          <p className="text-sm font-medium text-gray-500">No cross-asset event correlations detected in the current window.</p>
          <p className="mt-1 text-xs text-gray-400">Events need to impact both TradFi and crypto assets simultaneously.</p>
        </div>
      )}
    </section>
  );
}
