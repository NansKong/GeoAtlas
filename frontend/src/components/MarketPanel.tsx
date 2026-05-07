"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { Activity, Search, TrendingDown, TrendingUp } from "lucide-react";

import {
  fetchMarketFundamentals,
  fetchMarketOHLCV,
  fetchMarketQuote,
  getMarketWsUrl,
  MarketQuote,
  MarketStreamPriceUpdate,
  OHLCVPoint,
} from "@/lib/api";

const QUICK_TICKERS = ["NVDA", "AMD", "TSM", "SPY", "QQQ", "XOM", "BTC"];

function toAscending(points: OHLCVPoint[]): OHLCVPoint[] {
  return [...points].sort((a, b) => +new Date(a.timestamp) - +new Date(b.timestamp));
}

function compactNumber(value?: number): string {
  if (value === undefined || value === null) return "N/A";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function MiniPriceChart({ points }: { points: OHLCVPoint[] }) {
  if (!points.length) {
    return (
      <div className="h-36 rounded-2xl bg-gray-50 border border-gray-200 flex items-center justify-center text-sm text-gray-400">
        No chart data available
      </div>
    );
  }

  const ordered = toAscending(points);
  const closes = ordered.map((point) => point.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const width = 560;
  const height = 170;
  const padding = 12;
  const plotWidth = width - padding * 2;
  const plotHeight = height - padding * 2;
  const range = Math.max(max - min, 0.000001);

  const coords = closes.map((close, index) => {
    const x = padding + (index / Math.max(closes.length - 1, 1)) * plotWidth;
    const y = padding + (1 - (close - min) / range) * plotHeight;
    return { x, y };
  });
  const polylinePoints = coords.map((point) => `${point.x},${point.y}`).join(" ");
  const lastCoord = coords[coords.length - 1];

  const isUp = closes[closes.length - 1] >= closes[0];
  const stroke = isUp ? "#0f766e" : "#be123c";
  const fill = isUp ? "rgba(13,148,136,0.12)" : "rgba(225,29,72,0.12)";

  const areaPath = [
    `M ${coords[0].x},${coords[0].y}`,
    ...coords.slice(1).map((point) => `L ${point.x},${point.y}`),
    `L ${padding + plotWidth},${height - padding}`,
    `L ${padding},${height - padding}`,
    "Z",
  ].join(" ");

  const lastTimestampRaw = ordered[ordered.length - 1]?.timestamp;
  const lastTimestamp = lastTimestampRaw ? new Date(lastTimestampRaw) : null;
  const asOfLabel =
    lastTimestamp && !Number.isNaN(+lastTimestamp)
      ? lastTimestamp.toLocaleString([], {
          month: "short",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        })
      : null;
  const labelOnRight = lastCoord.x <= width - 130;
  const labelX = labelOnRight ? lastCoord.x + 8 : lastCoord.x - 8;
  const labelY = Math.max(padding + 10, lastCoord.y - 8);
  const textAnchor: "start" | "end" = labelOnRight ? "start" : "end";

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-40 rounded-2xl bg-white border border-gray-200">
      <defs>
        <linearGradient id="marketAreaFade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.24" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <rect x="0" y="0" width={width} height={height} fill="transparent" />
      <path d={areaPath} fill={fill} />
      <path d={areaPath} fill="url(#marketAreaFade)" />
      <polyline points={polylinePoints} fill="none" stroke={stroke} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastCoord.x} cy={lastCoord.y} r="4.5" fill={stroke} />
      {asOfLabel && (
        <text x={labelX} y={labelY} fill="#6b7280" fontSize="10" textAnchor={textAnchor}>
          as of {asOfLabel}
        </text>
      )}
    </svg>
  );
}

function mergeLivePoint(points: OHLCVPoint[], quote?: MarketQuote | null): OHLCVPoint[] {
  if (!points.length || !quote) return points;
  const ordered = toAscending(points);
  const quoteTs = +new Date(quote.as_of);
  const lastIdx = ordered.length - 1;
  const lastTs = +new Date(ordered[lastIdx].timestamp);

  if (Number.isNaN(quoteTs)) return ordered;

  if (quoteTs <= lastTs + 60_000) {
    const updatedLast = { ...ordered[lastIdx], close: quote.price };
    return [...ordered.slice(0, lastIdx), updatedLast];
  }

  return [
    ...ordered,
    {
      timestamp: quote.as_of,
      close: quote.price,
    },
  ];
}

export function MarketPanel({ customTicker }: { customTicker?: string }) {
  const [internalTicker, setInternalTicker] = useState("NVDA");
  const activeTicker = customTicker || internalTicker;
  const [streamQuote, setStreamQuote] = useState<MarketQuote | null>(null);
  const [streamStatus, setStreamStatus] = useState<"connecting" | "live" | "offline">("connecting");

  const quoteQuery = useQuery({
    queryKey: ["market-quote", activeTicker],
    queryFn: () => fetchMarketQuote(activeTicker),
    refetchInterval: streamStatus === "live" ? 60000 : 15000,
    staleTime: 8000,
  });

  const ohlcvQuery = useQuery({
    queryKey: ["market-ohlcv", activeTicker, 30],
    queryFn: () => fetchMarketOHLCV(activeTicker, { interval: "1day", limit: 30 }),
    staleTime: 45000,
  });

  const fundamentalsQuery = useQuery({
    queryKey: ["market-fundamentals", activeTicker],
    queryFn: () => fetchMarketFundamentals(activeTicker),
    staleTime: 6 * 60 * 60 * 1000,
  });

  useEffect(() => {
    setStreamQuote(null);
    setStreamStatus("connecting");

    const ws = new WebSocket(getMarketWsUrl([activeTicker]));
    ws.onopen = () => setStreamStatus("live");
    ws.onerror = () => setStreamStatus("offline");
    ws.onclose = () => setStreamStatus("offline");
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as Partial<MarketStreamPriceUpdate> & { type?: string };
        if (payload.type !== "price_update") return;
        if (!payload.ticker || payload.ticker !== activeTicker) return;
        if (typeof payload.price !== "number" || typeof payload.as_of !== "string") return;

        setStreamQuote({
          ticker: payload.ticker,
          price: payload.price,
          currency: payload.currency ?? "USD",
          as_of: payload.as_of,
          source: payload.source ?? "stream",
          cache_hit: false,
        });
      } catch {
        // Ignore non-JSON or control messages.
      }
    };

    return () => {
      ws.close();
    };
  }, [activeTicker]);

  const activeQuote = streamQuote ?? quoteQuery.data;
  const orderedPoints = ohlcvQuery.data?.points ? mergeLivePoint(ohlcvQuery.data.points, activeQuote) : [];
  const prevClose = orderedPoints.length >= 2 ? orderedPoints[orderedPoints.length - 2].close : undefined;
  const lastClose = activeQuote?.price ?? (orderedPoints.length >= 1 ? orderedPoints[orderedPoints.length - 1].close : undefined);
  const delta = prevClose !== undefined && lastClose !== undefined ? lastClose - prevClose : undefined;
  const deltaPct = prevClose && delta !== undefined ? (delta / prevClose) * 100 : undefined;
  const isUp = (delta ?? 0) >= 0;

  const [inputTicker, setInputTicker] = useState(activeTicker);

  useEffect(() => {
    setInputTicker(activeTicker);
  }, [activeTicker]);

  const onApplyTicker = () => {
    const normalized = inputTicker.trim().toUpperCase();
    if (normalized && !customTicker) {
      setInternalTicker(normalized);
    }
  };

  return (
    <section className="mb-7 rounded-[1.4rem] bg-gradient-to-br from-white via-[#f5faf9] to-[#edf5ff] border border-gray-200 p-4 md:p-5 shadow-sm">
      <div className="flex flex-col gap-4">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-geo-600" />
            <h2 className="text-base md:text-lg font-bold text-gray-900">Market Pulse</h2>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                value={inputTicker}
                onChange={(e) => setInputTicker(e.target.value.toUpperCase())}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onApplyTicker();
                }}
                className="pl-8 pr-3 h-9 w-28 md:w-32 rounded-full border border-gray-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-geo-300"
                placeholder="Ticker"
              />
            </div>
            <button
              onClick={onApplyTicker}
              className="h-9 px-3 rounded-full bg-geo-600 text-white text-sm font-semibold hover:bg-geo-700 transition-colors"
            >
              Load
            </button>
          </div>
        </div>

        {!customTicker && (
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            {QUICK_TICKERS.map((ticker) => (
              <button
                key={ticker}
                onClick={() => {
                  setInputTicker(ticker);
                  setInternalTicker(ticker);
                }}
                className={`shrink-0 px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors ${
                  activeTicker === ticker
                    ? "bg-gray-900 text-white border-gray-900"
                    : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                }`}
              >
                {ticker}
              </button>
            ))}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-[270px_1fr] gap-4">
          <div className="rounded-2xl border border-gray-200 bg-white p-4">
            <p className="text-xs uppercase tracking-wide text-gray-400 mb-2">{activeTicker}</p>
            {quoteQuery.isLoading ? (
              <div className="h-9 w-32 rounded bg-gray-100 animate-pulse" />
            ) : quoteQuery.isError || !activeQuote ? (
              <p className="text-sm text-red-600">Quote unavailable for {activeTicker}</p>
            ) : (
              <>
                <p className="text-3xl font-bold text-gray-900">
                  {activeQuote.currency} {activeQuote.price.toFixed(2)}
                </p>
                {delta !== undefined && deltaPct !== undefined && (
                  <div className={`mt-2 inline-flex items-center gap-1 text-sm font-semibold ${isUp ? "text-teal-700" : "text-rose-700"}`}>
                    {isUp ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                    {delta >= 0 ? "+" : ""}
                    {delta.toFixed(2)} ({deltaPct >= 0 ? "+" : ""}
                    {deltaPct.toFixed(2)}%)
                  </div>
                )}
                <div className="mt-3 text-xs text-gray-500 space-y-1">
                  <p>Source: {activeQuote.source}</p>
                  <p>Cache: {activeQuote.cache_hit ? "hit" : "miss"}</p>
                  <p>Stream: {streamStatus}</p>
                  <p>Updated: {formatDistanceToNow(new Date(activeQuote.as_of), { addSuffix: true })}</p>
                </div>
                <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2">
                  {fundamentalsQuery.isLoading ? (
                    <p className="text-xs text-gray-400">Loading fundamentals...</p>
                  ) : fundamentalsQuery.isError || !fundamentalsQuery.data ? (
                    <p className="text-xs text-gray-400">Fundamentals unavailable</p>
                  ) : (
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-gray-600">
                      <p>Mkt Cap: {compactNumber(fundamentalsQuery.data.market_cap)}</p>
                      <p>P/E: {fundamentalsQuery.data.pe_ratio?.toFixed(2) ?? "N/A"}</p>
                      <p>EPS: {fundamentalsQuery.data.eps?.toFixed(2) ?? "N/A"}</p>
                      <p>Div Yld: {fundamentalsQuery.data.dividend_yield?.toFixed(2) ?? "N/A"}%</p>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

          <div className="rounded-2xl border border-gray-200 bg-white p-3">
            {ohlcvQuery.isLoading ? (
              <div className="h-40 rounded-2xl bg-gray-100 animate-pulse" />
            ) : ohlcvQuery.isError || !ohlcvQuery.data ? (
              <div className="h-40 rounded-2xl border border-red-200 bg-red-50 text-red-700 text-sm flex items-center justify-center">
                OHLCV unavailable for {activeTicker}
              </div>
            ) : (
              <>
                <MiniPriceChart points={orderedPoints} />
                <div className="mt-2 text-xs text-gray-500 flex items-center justify-between">
                  <span>Last 30 trading days + live tick</span>
                  <span>
                    {ohlcvQuery.data.source} · {ohlcvQuery.data.cache_hit ? "cache hit" : "fresh"}
                  </span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
