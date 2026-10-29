"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { safeDate, safeDistanceToNow } from "@/lib/dateUtils";
import { Activity, Search, TrendingDown, TrendingUp, Wifi, WifiOff } from "lucide-react";

import {
  fetchMarketFundamentals,
  fetchMarketOHLCV,
  fetchMarketQuote,
  fetchMarketSnapshot,
  getMarketWsUrl,
  MarketQuote,
  MarketStreamPriceUpdate,
  OHLCVPoint,
} from "@/lib/api";

const QUICK_TICKERS = ["NVDA", "AMD", "TSM", "SPY", "QQQ", "XOM", "BTC"];

function toAscending(points: OHLCVPoint[]): OHLCVPoint[] {
  return [...points].sort((a, b) => {
    const ta = safeDate(a.timestamp)?.getTime() ?? 0;
    const tb = safeDate(b.timestamp)?.getTime() ?? 0;
    return ta - tb;
  });
}

function compactNumber(value?: number): string {
  if (value === undefined || value === null) return "N/A";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function mergeLivePoint(points: OHLCVPoint[], quote?: MarketQuote | null): OHLCVPoint[] {
  if (!points.length || !quote || typeof quote.price !== "number" || isNaN(quote.price)) return points;
  const ordered = toAscending(points);
  const quoteDate = safeDate(quote.as_of);
  if (!quoteDate) return ordered;
  const quoteTs = quoteDate.getTime();
  const lastIdx = ordered.length - 1;
  const lastDate = safeDate(ordered[lastIdx]?.timestamp);
  const lastTs = lastDate ? lastDate.getTime() : 0;
  if (quoteTs <= lastTs + 60_000) {
    return [...ordered.slice(0, lastIdx), { ...ordered[lastIdx], close: quote.price }];
  }
  return [...ordered, { timestamp: quote.as_of, close: quote.price }];
}

// ── Professional Light Theme Chart ───────────────────────────────────────────
function PriceChart({ points, ticker }: { points: OHLCVPoint[]; ticker: string }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const ordered = toAscending(points).filter(
    (p) => p && typeof p.close === "number" && !isNaN(p.close)
  );

  if (!ordered.length) {
    return (
      <div className="h-full min-h-[240px] rounded-2xl flex items-center justify-center text-sm text-gray-400 bg-white">
        No chart data available
      </div>
    );
  }

  const closes = ordered.map((p) => p.close);
  const isUp = closes[closes.length - 1] >= closes[0];

  // Layout
  const W = 800, H = 280;
  const padL = 16, padR = 80, padT = 22, padB = 34;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const minClose = Math.min(...closes);
  const maxClose = Math.max(...closes);
  const range = Math.max(maxClose - minClose, 0.000001);
  // Add padding top and bottom so line doesn't hit top/bottom edges
  const paddedMin = minClose - range * 0.08;
  const paddedMax = maxClose + range * 0.12;
  const paddedRange = paddedMax - paddedMin;

  const toX = (i: number) => padL + (i / Math.max(closes.length - 1, 1)) * plotW;
  const toY = (v: number) => padT + (1 - (v - paddedMin) / paddedRange) * plotH;

  const coords = closes.map((c, i) => ({ x: toX(i), y: toY(c) }));
  const lastPt = coords[coords.length - 1];
  const lastPrice = closes[closes.length - 1];
  const selectedIndex = hoverIndex !== null && hoverIndex < coords.length ? hoverIndex : null;
  const selectedPoint = selectedIndex !== null ? coords[selectedIndex] : null;
  const selectedDate = selectedIndex !== null ? safeDate(ordered[selectedIndex].timestamp) : null;
  const selectedPrice = selectedIndex !== null ? closes[selectedIndex] : null;

  const linePath = coords.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x},${p.y}`).join(" ");
  const areaPath = [
    linePath,
    `L ${lastPt.x},${padT + plotH}`,
    `L ${padL},${padT + plotH}`,
    "Z",
  ].join(" ");

  // Y-axis grid lines (4 levels)
  const yLevels = 4;
  const gridLines = Array.from({ length: yLevels + 1 }, (_, i) => {
    const fraction = i / yLevels;
    const value = paddedMax - fraction * paddedRange;
    const y = padT + fraction * plotH;
    return { y, value };
  });

  // X-axis time labels (5 evenly spaced)
  const xLabels = [0, 0.25, 0.5, 0.75, 1].map((frac) => {
    const idx = Math.round(frac * (ordered.length - 1));
    const ts = ordered[idx]?.timestamp;
    const d = safeDate(ts);
    const label = d
      ? d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
      : "";
    return { x: toX(idx), label };
  });

  const stroke = isUp ? "#078f70" : "#e64867";
  const gradientId = `grad-${ticker}`;
  const glowId = `glow-${ticker}`;

  // Current price label — clamp so it doesn't overflow top/bottom
  const labelY = Math.max(padT + 12, Math.min(lastPt.y, padT + plotH - 8));

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-full"
      preserveAspectRatio="none"
      aria-label={`${ticker} price chart`}
      onPointerMove={(event) => {
        const bounds = svgRef.current?.getBoundingClientRect();
        if (!bounds) return;
        const x = ((event.clientX - bounds.left) / bounds.width) * W;
        setHoverIndex(Math.max(0, Math.min(ordered.length - 1, Math.round(((x - padL) / plotW) * (ordered.length - 1)))));
      }}
      onPointerLeave={() => setHoverIndex(null)}
      style={{ touchAction: "pan-y", cursor: "crosshair" }}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.22" />
          <stop offset="75%" stopColor={stroke} stopOpacity="0.03" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
        <filter id={glowId} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <rect x="0" y="0" width={W} height={H} rx="16" fill="#f4faf7" />

      {/* Dashed horizontal grid lines + Y labels */}
      {gridLines.map(({ y, value }) => (
        <g key={y}>
          <line
            x1={padL} y1={y} x2={padL + plotW} y2={y}
            stroke="#dcebe5" strokeWidth="1" strokeDasharray="5,6"
          />
          <text
            x={padL + plotW + 6} y={y + 4}
            fill="#638078" fontSize="12" textAnchor="start" fontWeight="600"
          >
            {value >= 1000
              ? value.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })
              : value.toFixed(2)}
          </text>
        </g>
      ))}

      {/* Area fill */}
      <path d={areaPath} fill={`url(#${gradientId})`} />

      {/* Price line */}
      <path
        d={linePath}
        fill="none"
        stroke={stroke}
        strokeWidth="3"
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {/* Vertical line at last point */}
      <line
        x1={lastPt.x} y1={padT} x2={lastPt.x} y2={padT + plotH}
        stroke="#b6d5ca" strokeWidth="1" strokeDasharray="3,4"
      />

      {/* Glowing dot */}
      <circle cx={lastPt.x} cy={lastPt.y} r="6" fill={stroke} opacity="0.25" filter={`url(#${glowId})`} />
      <circle cx={lastPt.x} cy={lastPt.y} r="3.5" fill={stroke} />

      {selectedPoint && selectedPrice !== null && (
        <g pointerEvents="none">
          <line x1={selectedPoint.x} y1={padT} x2={selectedPoint.x} y2={padT + plotH} stroke="#416d64" strokeWidth="1.5" strokeDasharray="4,4" />
          <circle cx={selectedPoint.x} cy={selectedPoint.y} r="7" fill="white" stroke={stroke} strokeWidth="3" />
          <rect x={Math.max(4, Math.min(selectedPoint.x - 66, W - 140))} y={Math.max(4, selectedPoint.y - 52)} width="132" height="39" rx="8" fill="#102b2b" />
          <text x={Math.max(10, Math.min(selectedPoint.x - 60, W - 134))} y={Math.max(18, selectedPoint.y - 34)} fill="white" fontSize="13" fontWeight="700">{selectedPrice.toFixed(2)} {ticker === "BTC" ? "USD" : ""}</text>
          <text x={Math.max(10, Math.min(selectedPoint.x - 60, W - 134))} y={Math.max(31, selectedPoint.y - 19)} fill="#a6d5cc" fontSize="10">{selectedDate?.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</text>
        </g>
      )}

      {/* Current price badge on the right */}
      <rect
        x={padL + plotW + 2} y={labelY - 9}
        width={padR - 4} height={16}
        rx="4" fill={stroke}
      />
      <text
        x={padL + plotW + padR / 2} y={labelY + 3}
        fill="#fff" fontSize="11" fontWeight="700" textAnchor="middle"
      >
        {(lastPrice ?? 0) >= 1000
          ? (lastPrice ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
          : (lastPrice ?? 0).toFixed(2)}
      </text>

      {/* X-axis time labels */}
      {xLabels.map(({ x, label }) => (
        <text key={x} x={x} y={H - 7} fill="#638078" fontSize="12" textAnchor="middle" fontWeight="600">
          {label}
        </text>
      ))}
    </svg>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function MarketPanel({ customTicker }: { customTicker?: string }) {
  const [internalTicker, setInternalTicker] = useState(customTicker || "NVDA");
  const [inputTicker, setInputTicker] = useState(customTicker || "NVDA");
  const [streamQuote, setStreamQuote] = useState<MarketQuote | null>(null);
  const [streamStatus, setStreamStatus] = useState<"connecting" | "live" | "offline">("connecting");

  useEffect(() => {
    if (customTicker) {
      setInternalTicker(customTicker);
      setInputTicker(customTicker);
    }
  }, [customTicker]);

  const activeTicker = internalTicker;

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
  const snapshotQuery = useQuery({
    queryKey: ["market-snapshot", activeTicker],
    queryFn: fetchMarketSnapshot,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let isMounted = true;
    let retryDelay = 1500;

    setStreamQuote(null);

    function connect() {
      if (!isMounted) return;
      setStreamStatus("connecting");
      try {
        ws = new WebSocket(getMarketWsUrl([activeTicker]));
      } catch {
        setStreamStatus("offline");
        scheduleReconnect();
        return;
      }

      ws.onopen = () => {
        if (!isMounted) return;
        setStreamStatus("live");
        retryDelay = 1500;
      };

      ws.onerror = () => {
        if (!isMounted) return;
        setStreamStatus("offline");
      };

      ws.onclose = () => {
        if (!isMounted) return;
        setStreamStatus("offline");
        scheduleReconnect();
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as Partial<MarketStreamPriceUpdate> & { type?: string };
          if (payload.type !== "price_update" || payload.ticker !== activeTicker) return;
          if (typeof payload.price !== "number" || typeof payload.as_of !== "string") return;
          setStreamQuote({
            ticker: payload.ticker,
            price: payload.price,
            currency: payload.currency ?? "USD",
            as_of: payload.as_of,
            source: payload.source ?? "stream",
            cache_hit: false,
          });
        } catch { /* ignore */ }
      };
    }

    function scheduleReconnect() {
      if (!isMounted) return;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      reconnectTimeout = setTimeout(() => {
        if (isMounted) {
          retryDelay = Math.min(retryDelay * 1.5, 30000);
          connect();
        }
      }, retryDelay);
    }

    connect();

    return () => {
      isMounted = false;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (ws) ws.close();
    };
  }, [activeTicker]);

  const activeQuote = streamQuote ?? quoteQuery.data;
  const orderedPoints = ohlcvQuery.data?.points ? mergeLivePoint(ohlcvQuery.data.points, activeQuote) : [];
  const snapshotItem = snapshotQuery.data?.snapshot?.find((item) => item.ticker === activeTicker);
  const dailyPoints = toAscending(ohlcvQuery.data?.points ?? []);
  const latestDaily = dailyPoints[dailyPoints.length - 1];
  const prevClose = dailyPoints.length >= 2 ? dailyPoints[dailyPoints.length - 2].close : undefined;
  const lastClose = activeQuote?.price ?? (orderedPoints.length >= 1 ? orderedPoints[orderedPoints.length - 1].close : undefined);
  const historyDelta = prevClose !== undefined && lastClose !== undefined && latestDaily
    ? lastClose - prevClose : undefined;
  const historyDeltaPct = prevClose && historyDelta !== undefined ? (historyDelta / prevClose) * 100 : undefined;
  const deltaPct = snapshotItem && Number.isFinite(snapshotItem.change) ? snapshotItem.change : historyDeltaPct;
  const delta = deltaPct !== undefined && lastClose !== undefined
    ? lastClose * deltaPct / (100 + deltaPct) : historyDelta;
  const isUp = (delta ?? 0) >= 0;
  const firstTrendClose = orderedPoints[0]?.close;
  const lastTrendClose = orderedPoints[orderedPoints.length - 1]?.close;
  const trend30dPct = firstTrendClose && lastTrendClose
    ? ((lastTrendClose - firstTrendClose) / firstTrendClose) * 100
    : undefined;
  const chartLow = orderedPoints.length ? Math.min(...orderedPoints.map((point) => point.close)) : undefined;
  const chartHigh = orderedPoints.length ? Math.max(...orderedPoints.map((point) => point.close)) : undefined;

  const onApplyTicker = () => {
    const n = inputTicker.trim().toUpperCase();
    if (n) setInternalTicker(n);
  };

  const StreamIcon = streamStatus === "live" ? Wifi : WifiOff;
  const streamColor = streamStatus === "live" ? "text-emerald-500" : "text-gray-400";

  return (
    <section className="ga-market-panel mb-7 rounded-[1.4rem] border border-gray-200 overflow-hidden shadow-sm bg-white">
      {/* Header bar */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 px-5 py-4 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-emerald-600" />
          <h2 className="text-base font-bold text-gray-900">Market Pulse</h2>
          <span className={`ml-1 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide ${streamColor}`}>
            <StreamIcon className="w-3 h-3" />
            {streamStatus}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              value={inputTicker}
              onChange={(e) => setInputTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => { if (e.key === "Enter") onApplyTicker(); }}
              className="pl-8 pr-3 h-9 w-28 md:w-32 rounded-full border border-gray-200 bg-gray-50 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-emerald-300"
              placeholder="Ticker"
            />
          </div>
          <button
            onClick={onApplyTicker}
            className="h-9 px-4 rounded-full bg-gray-900 text-white text-sm font-semibold hover:bg-gray-700 transition-colors"
          >
            Load
          </button>
        </div>
      </div>

      {/* Quick tickers */}
      {!customTicker && (
        <div className="flex items-center gap-2 overflow-x-auto px-5 py-2.5 border-b border-gray-100 scrollbar-none">
          {QUICK_TICKERS.map((t) => (
            <button
              key={t}
              onClick={() => { setInputTicker(t); setInternalTicker(t); }}
              className={`shrink-0 px-3 py-1 rounded-full text-xs font-bold border transition-all ${
                activeTicker === t
                  ? "bg-gray-900 text-white border-gray-900"
                  : "bg-white text-gray-600 border-gray-200 hover:border-gray-400"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      {/* Body: left stats + right chart */}
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(230px,300px)_minmax(0,1fr)] items-stretch">
        {/* Left: price + fundamentals */}
        <div className="p-5 border-b lg:border-b-0 lg:border-r border-gray-100 flex flex-col justify-between">
          <div>
            <p className="text-xs uppercase tracking-widest text-gray-400 font-bold mb-3">{activeTicker}</p>

            {quoteQuery.isLoading ? (
              <div className="space-y-2">
                <div className="h-10 w-40 rounded-lg bg-gray-100 animate-pulse" />
                <div className="h-5 w-28 rounded bg-gray-100 animate-pulse" />
              </div>
            ) : quoteQuery.isError || !activeQuote ? (
              <p className="text-sm text-red-500">Quote unavailable</p>
            ) : (
              <>
                <p className="text-4xl font-black text-gray-900 tracking-tight tabular-nums">
                  {(activeQuote.price ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </p>
                <p className="text-xs text-gray-400 mt-0.5 font-medium">{activeQuote.currency}</p>

                {delta !== undefined && deltaPct !== undefined && (
                  <div className={`mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-bold ${
                    isUp ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
                  }`}>
                    {isUp ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                    {delta >= 0 ? "+" : ""}{(delta ?? 0).toFixed(2)} ({deltaPct >= 0 ? "+" : ""}{(deltaPct ?? 0).toFixed(2)}%)
                  </div>
                )}

                <div className="mt-4 space-y-1 text-xs text-gray-400">
                  <p>Source: <span className="text-gray-600 font-medium">{activeQuote.source}</span></p>
                  <p>Updated: <span className="text-gray-600 font-medium">{safeDistanceToNow(activeQuote.as_of)}</span></p>
                </div>
              </>
            )}
          </div>

          {/* Fundamentals */}
          <div className="mt-4 rounded-xl border border-gray-100 bg-gray-50 px-3 py-2.5">
            {fundamentalsQuery.isLoading ? (
              <p className="text-xs text-gray-400">Loading...</p>
            ) : fundamentalsQuery.data ? (
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-[11px]">
                {[
                  ["Mkt Cap", compactNumber(fundamentalsQuery.data.market_cap)],
                  ["P/E", fundamentalsQuery.data.pe_ratio?.toFixed(2) ?? "N/A"],
                  ["EPS", fundamentalsQuery.data.eps?.toFixed(2) ?? "N/A"],
                  ["Div Yld", fundamentalsQuery.data.dividend_yield
                    ? `${fundamentalsQuery.data.dividend_yield.toFixed(2)}%`
                    : "N/A"],
                ].map(([label, value]) => (
                  <div key={label}>
                    <span className="text-gray-400 block">{label}</span>
                    <span className="text-gray-800 font-bold">{value}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400">Fundamentals unavailable</p>
            )}
          </div>
        </div>

        {/* Right: white chart filling height */}
        <div className="ga-market-chart-wrap p-4 sm:p-6 flex min-w-0 flex-col justify-between relative overflow-hidden">
          {ohlcvQuery.isLoading ? (
            <div className="min-h-[260px] flex items-center justify-center">
              <div className="w-8 h-8 rounded-full border-2 border-emerald-500 border-t-transparent animate-spin" />
            </div>
          ) : ohlcvQuery.isError || !ohlcvQuery.data ? (
            <div className="min-h-[260px] flex items-center justify-center text-sm text-gray-400">
              Chart unavailable for {activeTicker}
            </div>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-teal-600">Price movement</p>
                  <h3 className="mt-1 text-lg font-bold text-slate-900">{activeTicker} over 30 trading days</h3>
                </div>
                {trend30dPct !== undefined && <span className={`rounded-full px-3 py-1.5 text-sm font-bold tabular-nums ${trend30dPct >= 0 ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-700"}`}>{trend30dPct >= 0 ? "+" : ""}{trend30dPct.toFixed(2)}% over period</span>}
              </div>
              <div className="ga-market-chart h-[270px] w-full sm:h-[310px]">
                <PriceChart points={orderedPoints} ticker={activeTicker} />
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                <span>Low <strong className="ml-1 text-slate-800">{chartLow?.toFixed(2) ?? "—"}</strong></span>
                <span>High <strong className="ml-1 text-slate-800">{chartHigh?.toFixed(2) ?? "—"}</strong></span>
                <span>30 trading days · {ohlcvQuery.data.source}</span>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
