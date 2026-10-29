"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Anchor,
  ArrowDownRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  Compass,
  Download,
  ExternalLink,
  Globe,
  Globe2,
  Info,
  List,
  MapPin,
  Pause,
  Play,
  RotateCcw,
  Search,
  Share2,
  ShieldAlert,
  Sliders,
  TrendingUp,
  X,
} from "lucide-react";
import type { GeoJSONSource } from "maplibre-gl";

import {
  fetchEventHeatmap,
  fetchMaritimeChokepoints,
  fetchUnlocatedEvents,
  fetchEvents,
  fetchNews,
  fetchMe,
  type EventHeatmapPoint,
  type MaritimeChokepoint,
  type UnlocatedEventsSummary,
  type EventListItem,
} from "@/lib/api";
import {
  Map as MapComponent,
  useMap,
  MapMarker,
  MarkerContent,
  MarkerTooltip,
  MapControls,
  type MapRef,
} from "@/components/ui/map";
import { safeDistanceToNow } from "@/lib/dateUtils";

/* ─── Layer Definitions & Constants ───────────────────────────────────────── */
type MapLayerId = "baseline_surge" | "conflict" | "energy" | "sanctions" | "elections" | "significance";

interface LayerOption {
  id: MapLayerId;
  label: string;
  unit: string;
  description: string;
  event_type?: string;
}

const MAP_LAYERS: LayerOption[] = [
  {
    id: "baseline_surge",
    label: "Relative Surge",
    unit: "Laplace Multiple vs Non-Overlapping 30d Baseline",
    description: "Compares current window velocity against the prior 30-day baseline (smoothed, requires n ≥ 3).",
  },
  {
    id: "conflict",
    label: "Conflict Intensity",
    unit: "% Conflict & Kinetic Share",
    description: "War, missile strikes, territorial disputes, and kinetic confrontations.",
  },
  {
    id: "energy",
    label: "Energy & Chokepoints",
    unit: "Transit & Infrastructure Risk",
    description: "Refineries, LNG terminals, pipelines, and strategic maritime corridors.",
    event_type: "energy_disruption",
  },
  {
    id: "sanctions",
    label: "Sanctions & Trade",
    unit: "Policy Action Density",
    description: "Tariffs, trade embargoes, export controls, and currency restrictions.",
    event_type: "sanction",
  },
  {
    id: "elections",
    label: "Elections & Political",
    unit: "Transition Watch",
    description: "Upcoming legislative and presidential elections with sovereign risk.",
    event_type: "election",
  },
  {
    id: "significance",
    label: "Event Significance",
    unit: "Severity × Confidence",
    description: "Quantifies catalyst gravity based on validated entity severity and extraction confidence.",
  },
];

const ASSET_LENSES = [
  { ticker: "", label: "All Assets", icon: "🌐" },
  { ticker: "USO", label: "Crude / USO", icon: "🛢️" },
  { ticker: "GLD", label: "Gold / GLD", icon: "🥇" },
  { ticker: "TSM", label: "Semis / TSM", icon: "⚡" },
  { ticker: "BTC", label: "Crypto / BTC", icon: "₿" },
  { ticker: "LMT", label: "Defense / LMT", icon: "🛡️" },
  { ticker: "DXY", label: "Dollar / DXY", icon: "💵" },
];

const SEARCH_SUGGESTIONS = [
  { name: "Taiwan Strait", type: "waterway", coords: [119.5, 24.0] as [number, number], zoom: 4.8 },
  { name: "Strait of Hormuz", type: "chokepoint", coords: [56.25, 26.55] as [number, number], zoom: 5.2 },
  { name: "Bab el-Mandeb & Red Sea", type: "chokepoint", coords: [43.35, 12.6] as [number, number], zoom: 5.0 },
  { name: "Suez Canal", type: "chokepoint", coords: [32.35, 30.7] as [number, number], zoom: 5.2 },
  { name: "Strait of Malacca", type: "chokepoint", coords: [100.95, 3.2] as [number, number], zoom: 4.8 },
  { name: "Turkish Straits (Bosporus)", type: "chokepoint", coords: [29.05, 41.08] as [number, number], zoom: 5.0 },
  { name: "Panama Canal", type: "chokepoint", coords: [-79.55, 9.08] as [number, number], zoom: 5.2 },
  { name: "Israel", type: "country", coords: [34.85, 31.04] as [number, number], zoom: 4.5 },
  { name: "Iran", type: "country", coords: [53.68, 32.42] as [number, number], zoom: 3.5 },
  { name: "Ukraine", type: "country", coords: [31.16, 48.37] as [number, number], zoom: 3.8 },
  { name: "Russia", type: "country", coords: [105.31, 61.52] as [number, number], zoom: 2.2 },
  { name: "United States", type: "country", coords: [-95.71, 37.09] as [number, number], zoom: 2.8 },
  { name: "China", type: "country", coords: [104.19, 35.86] as [number, number], zoom: 2.8 },
  { name: "Taiwan", type: "country", coords: [120.96, 23.69] as [number, number], zoom: 5.0 },
];

/* ─── Types ───────────────────────────────────────────────────────────────── */
type GlobePoint = EventHeatmapPoint & { latitude: number; longitude: number };

/* ─── Helpers ─────────────────────────────────────────────────────────────── */
function formatPct(v?: number | null) {
  return v == null ? "-" : `${(v * 100).toFixed(1)}%`;
}

function formatDisplayTicker(ticker?: string): string {
  if (!ticker) return "";
  const cleaned = ticker.replace(/^\$/, "");
  return cleaned === "DX-Y.NYB" || cleaned.includes("DX-Y") ? "DXY" : cleaned;
}

function formatMultiple(ratio?: number | null, status?: string) {
  if (status === "building_baseline" || ratio == null) {
    return "Building baseline";
  }
  return `${ratio.toFixed(1)}× normal`;
}

function getChoroplethHeatValue(point: GlobePoint, layer: MapLayerId): number {
  if (layer === "baseline_surge") {
    if (point.baseline_status === "building_baseline" || point.baseline_ratio == null) {
      return 0.0; // Render neutral while collecting baseline history
    }
    return Math.min(4.0, Math.max(0.0, point.baseline_ratio));
  }
  if (layer === "conflict") {
    return point.conflict_share;
  }
  if (layer === "significance") {
    return Math.min(1.0, (point.avg_severity / 5.0) * point.avg_confidence);
  }
  return Math.min(1.0, Math.min(point.event_count / 12, 1.0) * 0.7 + (point.avg_severity / 5.0) * 0.3);
}

/* ─── Country Choropleth Layer ────────────────────────────────────────────── */
function CountryChoroplethLayer({
  points,
  activeLayer,
  colorblindMode,
  selectedCountry,
  onSelectCountry,
}: {
  points: GlobePoint[];
  activeLayer: MapLayerId;
  colorblindMode: boolean;
  selectedCountry: string | null;
  onSelectCountry: (countryName: string) => void;
}) {
  const { map, isLoaded } = useMap();
  const id = useId();
  const sourceId = `countries-${id.replace(/:/g, "")}`;
  const fillId = `countries-fill-${id.replace(/:/g, "")}`;
  const lineId = `countries-line-${id.replace(/:/g, "")}`;

  const byCountry = useMemo(() => {
    const m = new Map<string, GlobePoint>();
    points.forEach((p) => {
      if (p.country && p.country !== "Unknown" && p.country !== "Global") {
        m.set(p.country.toLowerCase(), p);
      }
    });
    return m;
  }, [points]);

  useEffect(() => {
    if (!map || !isLoaded) return;
    let cancelled = false;

    async function load() {
      try {
        const resp = await fetch("/map-data/countries.geo.json");
        const raw = await resp.json();
        if (cancelled || !map) return;

        const enriched = {
          ...raw,
          features: raw.features.map((f: any) => {
            const name = String(f.properties?.name ?? "");
            const point = byCountry.get(name.toLowerCase());
            const heatVal = point ? getChoroplethHeatValue(point, activeLayer) : 0;
            const isSel = selectedCountry && name.toLowerCase() === selectedCountry.toLowerCase();
            return {
              ...f,
              properties: {
                ...f.properties,
                heat_value: heatVal,
                is_selected: isSel ? 1 : 0,
              },
            };
          }),
        };

        if (map.getSource(sourceId)) {
          (map.getSource(sourceId) as GeoJSONSource).setData(enriched);
          return;
        }

        map.addSource(sourceId, { type: "geojson", data: enriched });

        const standardColors = [
          "interpolate",
          ["linear"],
          ["get", "heat_value"],
          0.0, "rgba(15, 23, 42, 0.45)",
          0.8, "rgba(5, 150, 105, 0.4)",
          1.5, "rgba(217, 119, 6, 0.65)",
          2.3, "rgba(234, 88, 12, 0.8)",
          3.2, "rgba(225, 29, 72, 0.95)",
        ];

        const viridisColors = [
          "interpolate",
          ["linear"],
          ["get", "heat_value"],
          0.0, "rgba(68, 1, 84, 0.4)",
          0.8, "rgba(59, 82, 139, 0.55)",
          1.5, "rgba(33, 145, 140, 0.7)",
          2.3, "rgba(94, 201, 98, 0.85)",
          3.2, "rgba(253, 231, 37, 0.95)",
        ];

        map.addLayer(
          {
            id: fillId,
            type: "fill",
            source: sourceId,
            paint: {
              "fill-color": (colorblindMode ? viridisColors : standardColors) as any,
              "fill-opacity": [
                "case",
                ["==", ["get", "is_selected"], 1],
                0.95,
                0.75,
              ],
            },
          },
          map.getLayer("hotspot-heat") ? "hotspot-heat" : undefined
        );

        map.addLayer({
          id: lineId,
          type: "line",
          source: sourceId,
          paint: {
            "line-color": [
              "case",
              ["==", ["get", "is_selected"], 1],
              "#38bdf8",
              "rgba(71, 85, 105, 0.5)",
            ],
            "line-width": [
              "interpolate",
              ["linear"],
              ["zoom"],
              0,
              ["case", ["==", ["get", "is_selected"], 1], 2.2, 0.5],
              4,
              ["case", ["==", ["get", "is_selected"], 1], 3.0, 1.0],
            ],
          },
        });

        map.on("click", fillId, (e) => {
          const feature = e.features?.[0];
          const countryName = feature?.properties?.name;
          if (countryName) {
            onSelectCountry(countryName);
          }
        });

        map.on("mouseenter", fillId, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", fillId, () => {
          map.getCanvas().style.cursor = "";
        });
      } catch (err) {
        console.error("Failed to load country choropleth:", err);
      }
    }

    load();

    return () => {
      cancelled = true;
      try {
        if (map.getLayer(lineId)) map.removeLayer(lineId);
        if (map.getLayer(fillId)) map.removeLayer(fillId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
      } catch {
        /* ignore */
      }
    };
  }, [map, isLoaded, byCountry, activeLayer, colorblindMode, selectedCountry, onSelectCountry, sourceId, fillId, lineId]);

  return null;
}

/* ─── Heatmap Glow Layer ──────────────────────────────────────────────────── */
function HeatmapGlowLayer({ points }: { points: GlobePoint[] }) {
  const { map, isLoaded } = useMap();
  const id = useId();
  const sourceId = `heat-src-${id.replace(/:/g, "")}`;
  const layerId = `hotspot-heat`;

  const geoJson = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: points.map((p) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [p.longitude, p.latitude] },
        properties: {
          event_count: p.event_count,
          conflict_share: p.conflict_share,
          baseline_ratio: p.baseline_ratio ?? 1.0,
        },
      })),
    }),
    [points]
  );

  useEffect(() => {
    if (!map || !isLoaded) return;
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: "geojson", data: geoJson });
    } else {
      (map.getSource(sourceId) as GeoJSONSource).setData(geoJson);
    }

    if (!map.getLayer(layerId)) {
      map.addLayer({
        id: layerId,
        type: "heatmap",
        source: sourceId,
        maxzoom: 7,
        paint: {
          "heatmap-weight": ["interpolate", ["linear"], ["get", "baseline_ratio"], 1, 0.2, 3, 1],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 0.4, 4, 1.2],
          "heatmap-color": [
            "interpolate",
            ["linear"],
            ["heatmap-density"],
            0, "rgba(16,185,129,0)",
            0.25, "rgba(16,185,129,0.3)",
            0.5, "rgba(217,119,6,0.5)",
            0.75, "rgba(240,78,94,0.7)",
            1, "rgba(244,63,94,0.95)",
          ],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 16, 4, 34],
          "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 0, 0.55, 6, 0.25],
        },
      });
    }

    return () => {
      try {
        if (map.getLayer(layerId)) map.removeLayer(layerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
      } catch {
        /* ignore */
      }
    };
  }, [map, isLoaded, sourceId, layerId, geoJson]);

  return null;
}

/* ─── Hotspot Pin Marker ─────────────────────────────────────────────────── */
function HotspotDot({
  point,
  onClick,
}: {
  point: GlobePoint;
  onClick: (p: GlobePoint) => void;
}) {
  const isBuilding = point.baseline_status === "building_baseline" || point.baseline_ratio == null;
  const surge = point.baseline_ratio ?? 1.0;
  const isSurge = !isBuilding && surge >= 2.3;
  const color = isBuilding
    ? "#38bdf8"
    : surge >= 2.5
    ? "#f43f5e"
    : surge >= 1.6
    ? "#f59e0b"
    : "#10b981";

  const size = Math.max(12, Math.min(26, point.event_count * 1.4));

  return (
    <MapMarker longitude={point.longitude} latitude={point.latitude}>
      <MarkerContent>
        <button
          type="button"
          onClick={() => onClick(point)}
          className="relative flex items-center justify-center focus:outline-none transition-transform hover:scale-125 cursor-pointer"
          style={{ width: size * 2.2, height: size * 2.2 }}
          aria-label={`Hotspot in ${point.country}`}
        >
          {isSurge && (
            <div
              className="absolute inset-0 animate-ping rounded-full opacity-35"
              style={{ backgroundColor: color, animationDuration: "2.8s" }}
            />
          )}
          <div
            className="absolute rounded-full opacity-25"
            style={{ backgroundColor: color, width: size * 1.4, height: size * 1.4 }}
          />
          <div
            className="relative flex items-center justify-center rounded-full border border-white/70 shadow-lg"
            style={{
              backgroundColor: color,
              width: Math.max(8, size * 0.55),
              height: Math.max(8, size * 0.55),
              boxShadow: `0 0 12px ${color}aa`,
            }}
          >
            {point.event_count >= 8 && (
              <span className="text-[8px] font-black text-white leading-none">
                {point.event_count}
              </span>
            )}
          </div>
        </button>
      </MarkerContent>
      <MarkerTooltip offset={16} className="bg-slate-900 border border-slate-700 text-white shadow-xl rounded-xl p-2.5">
        <div className="flex items-center justify-between gap-3">
          <p className="font-bold text-white text-xs">{point.country}</p>
          <span
            className="rounded px-1.5 py-0.5 text-[10px] font-black uppercase tracking-wider"
            style={{
              backgroundColor: `${color}25`,
              color: color,
            }}
          >
            {point.source_basis === "news" ? "NEWS" : formatMultiple(point.baseline_ratio, point.baseline_status)}
          </span>
        </div>
        <p className="mt-1 text-[11px] text-slate-300 font-medium">
          {point.source_basis === "news"
            ? `${point.event_count} source articles · open for headlines`
            : `${point.event_count} events · sev ${point.avg_severity.toFixed(1)} · conflict ${(point.conflict_share * 100).toFixed(0)}%`}
        </p>
        <p className="mt-1 text-[9px] text-emerald-400 font-semibold uppercase tracking-wider">
          {point.source_basis === "news" ? "Click to read source reporting" : "Click to inspect timeline & affected assets"}
        </p>
      </MarkerTooltip>
    </MapMarker>
  );
}

/* ─── Maritime Chokepoint Pin Marker ──────────────────────────────────────── */
function ChokepointMarker({
  chokepoint,
  onClick,
}: {
  chokepoint: MaritimeChokepoint;
  onClick: (cp: MaritimeChokepoint) => void;
}) {
  const statusColor =
    chokepoint.status === "disrupted"
      ? "#ef4444"
      : chokepoint.status === "elevated"
      ? "#f59e0b"
      : "#10b981";

  const isAlert = chokepoint.status !== "normal";

  return (
    <MapMarker longitude={chokepoint.coordinates[0]} latitude={chokepoint.coordinates[1]}>
      <MarkerContent>
        <button
          type="button"
          onClick={() => onClick(chokepoint)}
          className="relative flex items-center justify-center p-1 focus:outline-none transition-transform hover:scale-125 cursor-pointer"
          aria-label={`Maritime chokepoint ${chokepoint.name}`}
        >
          {isAlert && (
            <div
              className="absolute inset-0 animate-ping rounded-full opacity-40"
              style={{ backgroundColor: statusColor, animationDuration: "2.2s" }}
            />
          )}
          <div
            className="relative flex items-center justify-center h-6 w-6 rounded-full border-2 border-white bg-slate-900 shadow-xl"
            style={{ borderColor: statusColor }}
          >
            <Anchor className="h-3 w-3" style={{ color: statusColor }} />
          </div>
        </button>
      </MarkerContent>
      <MarkerTooltip offset={18} className="bg-slate-950 border border-slate-700 text-white shadow-2xl rounded-xl p-3 max-w-[280px]">
        <div className="flex items-center justify-between gap-2 border-b border-slate-800 pb-1.5 mb-1.5">
          <div className="flex items-center gap-1.5">
            <Anchor className="h-3.5 w-3.5 text-cyan-400" />
            <span className="font-bold text-white text-xs">{chokepoint.name}</span>
          </div>
          <span
            className="rounded px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider"
            style={{
              backgroundColor: `${statusColor}25`,
              color: statusColor,
            }}
          >
            {chokepoint.status} (Rule-based)
          </span>
        </div>
        <p className="text-[10px] text-cyan-300 font-medium">{chokepoint.traffic_estimate}</p>
        <p className="mt-1 text-[11px] text-slate-300 line-clamp-2">{chokepoint.latest_headline ?? chokepoint.note}</p>
        <div className="mt-2 text-[9px] text-slate-500">
          <span>Source: </span>
          <a
            href={chokepoint.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-400 hover:text-cyan-400 underline"
            onClick={(e) => e.stopPropagation()}
          >
            {chokepoint.source_citation}
          </a>
        </div>
      </MarkerTooltip>
    </MapMarker>
  );
}

/* ─── Skeleton Globe Loader ───────────────────────────────────────────────── */
function SkeletonGlobe() {
  return (
    <div className="relative h-[680px] w-full overflow-hidden rounded-[28px] border border-slate-800 bg-slate-950 flex flex-col items-center justify-center p-8">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(16,185,129,0.08)_0%,transparent_70%)]" />
      <div className="relative flex flex-col items-center">
        <div className="relative flex items-center justify-center h-48 w-48">
          <div className="absolute inset-0 rounded-full border border-emerald-500/20 animate-ping" style={{ animationDuration: "3s" }} />
          <div className="absolute inset-4 rounded-full border border-emerald-500/30 animate-pulse" />
          <div className="absolute inset-10 rounded-full border border-emerald-500/40" />
          <div className="h-16 w-16 rounded-full bg-emerald-500/10 border border-emerald-400/50 flex items-center justify-center shadow-[0_0_30px_rgba(16,185,129,0.3)]">
            <Globe className="h-8 w-8 text-emerald-400 animate-spin" style={{ animationDuration: "12s" }} />
          </div>
        </div>
        <div className="mt-6 text-center">
          <p className="text-sm font-bold uppercase tracking-widest text-emerald-400">
            Synthesizing Macro Telemetry
          </p>
          <p className="mt-1.5 text-xs text-slate-400 max-w-sm">
            Fetching non-overlapping 30-day baseline ratios, anchored maritime chokepoints, and cross-asset links...
          </p>
        </div>
      </div>
    </div>
  );
}

/* ─── Failure State ───────────────────────────────────────────────────────── */
function MapFailureState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="relative h-[680px] w-full overflow-hidden rounded-[28px] border border-rose-900/50 bg-slate-950 flex flex-col items-center justify-center p-8">
      <div className="rounded-2xl border border-rose-800/60 bg-rose-950/40 p-6 text-center max-w-md shadow-2xl backdrop-blur-md">
        <AlertTriangle className="mx-auto h-10 w-10 text-rose-500 mb-3" />
        <h3 className="text-base font-bold text-white">Geopolitical Telemetry Unavailable</h3>
        <p className="mt-1.5 text-xs text-slate-300">
          The map engine could not load real-time heatmap layers from the API server. This might be caused by network instability or database sync.
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 inline-flex items-center gap-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold px-4 py-2 text-xs shadow-lg transition-all cursor-pointer"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Retry Connection
        </button>
      </div>
    </div>
  );
}

/* ─── Legend Overlay ──────────────────────────────────────────────────────── */
function LegendOverlay({
  layer,
  colorblind,
  onToggleColorblind,
}: {
  layer: LayerOption;
  colorblind: boolean;
  onToggleColorblind: () => void;
}) {
  return (
    <div className="absolute bottom-5 left-5 z-20 rounded-2xl border border-slate-700/80 bg-slate-900/95 backdrop-blur-md px-4 py-3 shadow-2xl text-xs text-white max-w-xs">
      <div className="flex items-center justify-between gap-3 border-b border-slate-800 pb-2 mb-2">
        <div>
          <p className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Active Layer</p>
          <p className="text-xs font-black text-white">{layer.label}</p>
        </div>
        <button
          type="button"
          onClick={onToggleColorblind}
          title="Toggle colorblind palette (Viridis)"
          className={`rounded-lg border px-2 py-1 text-[10px] font-bold transition-all cursor-pointer ${
            colorblind
              ? "border-amber-400 bg-amber-400/20 text-amber-300"
              : "border-slate-700 bg-slate-800 text-slate-400 hover:text-white"
          }`}
        >
          {colorblind ? "Viridis" : "Standard"}
        </button>
      </div>

      <p className="text-[11px] text-slate-300 mb-2 leading-tight">{layer.description}</p>

      {layer.id === "baseline_surge" ? (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[10px] text-slate-400 font-semibold">
            <span>Normal (1.0×)</span>
            <span>Elevated (1.6×)</span>
            <span>Surge (2.5×+)</span>
          </div>
          <div
            className="h-2.5 w-full rounded-full"
            style={{
              background: colorblind
                ? "linear-gradient(to right, #440154, #3b528b, #21918c, #5ec962, #fde725)"
                : "linear-gradient(to right, #059669, #d97706, #ea580c, #f43f5e)",
            }}
          />
          <p className="text-[9px] text-slate-400 text-center italic">
            *Countries with &lt; 3 window events marked &quot;Building baseline&quot;
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[10px] text-slate-400 font-semibold">
            <span>Low Impact</span>
            <span>Moderate</span>
            <span>High Severity</span>
          </div>
          <div
            className="h-2.5 w-full rounded-full"
            style={{
              background: colorblind
                ? "linear-gradient(to right, #440154, #21918c, #fde725)"
                : "linear-gradient(to right, #059669, #eab308, #f43f5e)",
            }}
          />
        </div>
      )}
    </div>
  );
}

/* ─── 30-Day Time Replay Bar ──────────────────────────────────────────────── */
function TimeReplayBar({
  dayOffset,
  setDayOffset,
  isPlaying,
  setIsPlaying,
  totalDays,
}: {
  dayOffset: number;
  setDayOffset: React.Dispatch<React.SetStateAction<number>>;
  isPlaying: boolean;
  setIsPlaying: React.Dispatch<React.SetStateAction<boolean>>;
  totalDays: number;
}) {
  useEffect(() => {
    if (!isPlaying) return;
    const interval = setInterval(() => {
      setDayOffset((prev) => {
        if (prev >= totalDays) {
          setIsPlaying(false);
          return totalDays;
        }
        return prev + 1;
      });
    }, 600);
    return () => clearInterval(interval);
  }, [isPlaying, totalDays, setDayOffset, setIsPlaying]);

  const dateLabel = useMemo(() => {
    const daysAgo = totalDays - dayOffset;
    if (daysAgo === 0) return "Today (Latest)";
    if (daysAgo === 1) return "1 day ago";
    return `${daysAgo} days ago`;
  }, [dayOffset, totalDays]);

  return (
    <div className="absolute bottom-5 right-5 z-20 flex items-center gap-3 rounded-2xl border border-slate-700/80 bg-slate-900/95 backdrop-blur-md px-4 py-2.5 shadow-2xl text-white">
      <button
        type="button"
        onClick={() => {
          if (dayOffset >= totalDays && !isPlaying) {
            setDayOffset(0);
          }
          setIsPlaying((prev) => !prev);
        }}
        className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold transition-all shadow-md cursor-pointer"
        title={isPlaying ? "Pause timeline replay" : "Play 30-day timeline replay"}
      >
        {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 ml-0.5" />}
      </button>

      <div className="flex flex-col">
        <div className="flex items-center justify-between text-[10px] font-bold text-slate-400 mb-1">
          <span>Replay: {dateLabel}</span>
          <span className="text-emerald-400 font-mono">Day {dayOffset}/{totalDays}</span>
        </div>
        <input
          type="range"
          min={0}
          max={totalDays}
          value={dayOffset}
          onChange={(e) => {
            setIsPlaying(false);
            setDayOffset(Number(e.target.value));
          }}
          className="h-1.5 w-40 cursor-pointer appearance-none rounded-lg bg-slate-700 accent-emerald-400"
        />
      </div>

      <button
        type="button"
        onClick={() => {
          setIsPlaying(false);
          setDayOffset(totalDays);
        }}
        className="text-[10px] uppercase font-bold text-slate-400 hover:text-white px-1.5 py-1 rounded bg-slate-800 cursor-pointer"
      >
        Reset
      </button>
    </div>
  );
}

/* ─── Country Intelligence Drawer (Desktop Slide-over / Mobile Bottom Sheet) ── */
function CountryIntelligenceDrawer({
  country,
  point,
  onClose,
  onFlyTo,
}: {
  country: string;
  point?: GlobePoint;
  onClose: () => void;
  onFlyTo: (coords: [number, number]) => void;
}) {
  const { data: events, isLoading } = useQuery({
    queryKey: ["country-events", country],
    queryFn: () => fetchEvents({ country, limit: 15, status: "published" }),
    enabled: !!country,
    staleTime: 60_000,
  });
  const { data: sourceNews, isLoading: newsLoading } = useQuery({
    queryKey: ["country-source-news", country],
    queryFn: () => fetchNews({ country, limit: 8 }),
    enabled: !!country && !!point?.source_basis,
    staleTime: 60_000,
  });

  const isBuilding = point?.baseline_status === "building_baseline" || point?.baseline_ratio == null;
  const surge = point?.baseline_ratio ?? 1.0;
  const isSurge = !isBuilding && surge >= 2.0;

  return (
    <div className="fixed inset-x-0 bottom-0 max-h-[85vh] sm:inset-y-0 sm:right-0 sm:left-auto sm:max-w-md sm:max-h-full w-full bg-slate-950 border-t sm:border-t-0 sm:border-l border-slate-800 text-white shadow-2xl flex flex-col overflow-hidden z-50 rounded-t-3xl sm:rounded-none animate-in slide-in-from-bottom sm:slide-in-from-right duration-300">
      {/* Drawer Header */}
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/80 px-6 py-4">
        <div>
          <div className="flex items-center gap-2">
            <Globe2 className="h-5 w-5 text-emerald-400" />
            <h2 className="text-lg font-black text-white tracking-tight">{country}</h2>
          </div>
          <p className="mt-0.5 text-xs text-slate-400 font-medium">Sovereign Geopolitical & Asset Dossier</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white transition-all cursor-pointer"
          aria-label="Close dossier"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Drawer Content */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
        {point?.source_basis === "news" ? (
          <div className="rounded-2xl border border-emerald-500/25 bg-emerald-500/10 p-4">
            <p className="text-[11px] font-bold uppercase tracking-wider text-emerald-300">Source coverage</p>
            <p className="mt-2 text-2xl font-black text-white">{point.event_count} articles</p>
            <p className="mt-2 text-xs leading-relaxed text-slate-300">This country appears in recent reporting. Article mentions are shown separately from approved events and do not confirm a local conflict.</p>
          </div>
        ) : (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/90 p-4 shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Baseline Velocity</span>
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-black tracking-wide ${
                isBuilding
                  ? "bg-sky-500/20 text-sky-300 border border-sky-500/40"
                  : isSurge
                  ? "bg-rose-500/20 text-rose-400 border border-rose-500/40"
                  : "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
              }`}
            >
              {formatMultiple(point?.baseline_ratio, point?.baseline_status)}
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 border-t border-slate-800 pt-3 mt-3 text-center">
            <div>
              <p className="text-[10px] text-slate-400 uppercase font-bold">Events</p>
              <p className="text-base font-black text-white">{point?.event_count ?? 0}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-400 uppercase font-bold">Prior 30d Base</p>
              <p className="text-base font-black text-slate-300">{point?.baseline_count ?? 0}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-400 uppercase font-bold">Conflict tagged</p>
              <p className="text-base font-black text-rose-400">{formatPct(point?.conflict_share)}</p>
            </div>
          </div>

          {isBuilding && (
            <p className="mt-2 text-[10px] text-slate-400 italic text-center">
              *Requires n ≥ 3 events in window before calculating ratio.
            </p>
          )}

          {point && point.latitude != null && point.longitude != null && (
            <button
              type="button"
              onClick={() => onFlyTo([point.longitude, point.latitude])}
              className="mt-4 w-full flex items-center justify-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800 hover:bg-slate-700 py-2 text-xs font-bold text-white transition-all cursor-pointer"
            >
              <Compass className="h-3.5 w-3.5 text-emerald-400" />
              Center Globe on {country}
            </button>
          )}
        </div>
        )}

        {/* Top Catalyst Events */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
              Active Catalysts ({events?.length ?? 0})
            </h3>
            <span className="text-[10px] text-emerald-400 font-semibold">Rule-grounded</span>
          </div>

          {isLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-20 animate-pulse rounded-2xl bg-slate-900 border border-slate-800" />
              ))}
            </div>
          ) : !events || events.length === 0 ? (
            <p className="text-xs text-slate-400">No approved structured events yet. Source reporting appears below when available.</p>
          ) : (
            <div className="space-y-3">
              {events.map((e) => (
                <div
                  key={e.id}
                  className="rounded-2xl border border-slate-800/90 bg-slate-900/60 hover:bg-slate-900 p-3.5 transition-all"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="rounded bg-slate-800 border border-slate-700 px-2 py-0.5 text-[9px] font-bold text-emerald-400 uppercase tracking-wider">
                      {e.event_type.replace(/_/g, " ")}
                    </span>
                    <span className="text-[10px] text-slate-500 font-medium">
                      {e.published_at ? safeDistanceToNow(e.published_at) : "Recent"}
                    </span>
                  </div>
                  <h4 className="mt-1.5 text-xs font-bold text-slate-100 line-clamp-2 leading-snug">
                    {e.title}
                  </h4>

                  {/* Affected Assets */}
                  {e.affected_assets && e.affected_assets.length > 0 && (
                    <div className="mt-2.5 pt-2 border-t border-slate-800/80 space-y-1">
                      <p className="text-[9px] uppercase tracking-wider text-slate-400 font-bold">
                        Linked Assets:
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {e.affected_assets.map((asset) => {
                          const isUp = asset.impact_direction === "up";
                          return (
                            <div
                              key={asset.ticker}
                              className={`flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] font-bold ${
                                isUp
                                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                                  : "border-rose-500/30 bg-rose-500/10 text-rose-400"
                              }`}
                              title={asset.rationale ?? undefined}
                            >
                              <span>{isUp ? "▲" : "▼"}</span>
                              <span>${formatDisplayTicker(asset.ticker)}</span>
                              {asset.magnitude && (
                                <span className="opacity-70 text-[8px] uppercase">({asset.magnitude})</span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">Latest source reporting</h3>
            <span className="text-[10px] text-slate-500">Articles are not verified incidents</span>
          </div>
          {newsLoading ? <div className="h-20 animate-pulse rounded-2xl bg-slate-900" /> : sourceNews?.length ? (
            <div className="space-y-2">
              {sourceNews.map((article) => (
                <a key={article.id} href={article.url} target="_blank" rel="noopener noreferrer" className="block rounded-2xl border border-slate-800 bg-slate-900/60 p-3.5 transition-colors hover:border-emerald-500/50 hover:bg-slate-900">
                  <span className="text-[10px] font-semibold text-emerald-300">{article.source} · {article.published_at ? safeDistanceToNow(article.published_at) : "Date unavailable"}</span>
                  <span className="mt-1 block text-xs font-semibold leading-snug text-white">{article.title}</span>
                </a>
              ))}
            </div>
          ) : <p className="text-xs text-slate-500">{point?.source_basis ? `No recent source articles for ${country} in this feed.` : "Source coverage will appear when the map feed updates."}</p>}
        </div>
      </div>
    </div>
  );
}

/* ─── Unlocated & Global Events Drawer ─────────────────────────────────────── */
function UnlocatedEventsDrawer({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const { data: summary, isLoading } = useQuery<UnlocatedEventsSummary>({
    queryKey: ["unlocated-events-summary"],
    queryFn: () => fetchUnlocatedEvents(70),
    enabled: isOpen,
    staleTime: 60_000,
  });

  const [activeTab, setActiveTab] = useState<"all" | "global" | "unknown">("all");

  const filtered = useMemo(() => {
    if (!summary?.events) return [];
    if (activeTab === "global") return summary.events.filter((e) => e.country === "Global");
    if (activeTab === "unknown") return summary.events.filter((e) => e.country !== "Global");
    return summary.events;
  }, [summary, activeTab]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 max-h-[85vh] sm:inset-y-0 sm:right-0 sm:left-auto sm:max-w-lg sm:max-h-full w-full bg-slate-950 border-t sm:border-t-0 sm:border-l border-slate-800 text-white shadow-2xl flex flex-col overflow-hidden z-50 rounded-t-3xl sm:rounded-none animate-in slide-in-from-bottom sm:slide-in-from-right duration-300">
      {/* Drawer Header */}
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/80 px-6 py-4">
        <div>
          <div className="flex items-center gap-2">
            <Compass className="h-5 w-5 text-cyan-400" />
            <h2 className="text-lg font-black text-white tracking-tight">
              Unlocated & Global Intelligence
            </h2>
          </div>
          <p className="mt-0.5 text-xs text-slate-400 font-medium">
            Decoupled from sovereign choropleths so baseline metrics remain statistically sound.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white transition-all cursor-pointer"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800 bg-slate-900/40 px-6 py-2 gap-2">
        <button
          type="button"
          onClick={() => setActiveTab("all")}
          className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-all cursor-pointer ${
            activeTab === "all" ? "bg-slate-800 text-white border border-slate-700" : "text-slate-400 hover:text-white"
          }`}
        >
          All ({summary?.total_unlocated ?? 0})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("global")}
          className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-all cursor-pointer ${
            activeTab === "global" ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40" : "text-slate-400 hover:text-white"
          }`}
        >
          Global Macro ({summary?.global_count ?? 39})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("unknown")}
          className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-all cursor-pointer ${
            activeTab === "unknown" ? "bg-amber-500/20 text-amber-300 border border-amber-500/40" : "text-slate-400 hover:text-white"
          }`}
        >
          Multi-region / Unlocated ({summary?.unknown_count ?? 96})
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-3">
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-2xl bg-slate-900 border border-slate-800" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-xs text-slate-500 italic">No events in this category.</p>
        ) : (
          filtered.map((e) => (
            <div
              key={e.id}
              className="rounded-2xl border border-slate-800/90 bg-slate-900/60 p-4 hover:bg-slate-900 transition-all"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="rounded bg-slate-800 border border-slate-700 px-2 py-0.5 text-[9px] font-bold text-cyan-400 uppercase tracking-wider">
                  {e.country === "Global" ? "GLOBAL MACRO" : "MULTI-REGION"}
                </span>
                <span className="text-[10px] text-slate-500">
                  {e.published_at ? safeDistanceToNow(e.published_at) : "Recent"}
                </span>
              </div>
              <h4 className="mt-1.5 text-xs font-bold text-slate-100 leading-snug">{e.title}</h4>

              {e.affected_assets && e.affected_assets.length > 0 && (
                <div className="mt-2.5 pt-2 border-t border-slate-800/80 flex flex-wrap gap-1.5">
                  {e.affected_assets.map((asset) => (
                    <div
                      key={asset.ticker}
                      className={`flex items-center gap-1 rounded-lg border px-2 py-0.5 text-[10px] font-bold ${
                        asset.impact_direction === "up"
                          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                          : "border-rose-500/30 bg-rose-500/10 text-rose-400"
                      }`}
                    >
                      <span>{asset.impact_direction === "up" ? "▲" : "▼"}</span>
                      <span>${asset.ticker}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/* ─── Accessible List View ────────────────────────────────────────────────── */
function AccessibleListView({
  points,
  onSelectCountry,
}: {
  points: GlobePoint[];
  onSelectCountry: (c: string) => void;
}) {
  return (
    <div className="h-[680px] w-full overflow-y-auto rounded-[28px] border border-slate-800 bg-slate-950 p-6 text-slate-100">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
        <div>
          <h2 className="text-base font-bold text-white">Sovereign Telemetry Table</h2>
          <p className="text-xs text-slate-400">Accessible tabular view of all active monitored countries and baseline ratios.</p>
        </div>
        <span className="text-xs font-bold text-emerald-400 font-mono">{points.length} Countries</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400 uppercase text-[10px] tracking-wider">
              <th className="py-2.5 px-3 font-bold">Country</th>
              <th className="py-2.5 px-3 font-bold">Window Count</th>
              <th className="py-2.5 px-3 font-bold">Baseline Ratio</th>
              <th className="py-2.5 px-3 font-bold">Conflict tagged</th>
              <th className="py-2.5 px-3 font-bold">Severity</th>
              <th className="py-2.5 px-3 font-bold text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-850">
            {points.map((p) => {
              const isBuilding = p.baseline_status === "building_baseline" || p.baseline_ratio == null;
              return (
                <tr key={p.country} className="hover:bg-slate-900/80 transition-colors">
                  <td className="py-3 px-3 font-bold text-white">{p.country}</td>
                  <td className="py-3 px-3 font-mono">{p.event_count} {p.source_basis === "news" ? "articles" : "events"}</td>
                  <td className="py-3 px-3">
                    <span
                      className={`inline-block rounded px-2 py-0.5 text-[10px] font-bold ${
                        isBuilding
                          ? "bg-slate-800 text-slate-300"
                          : (p.baseline_ratio ?? 1) >= 2.3
                          ? "bg-rose-500/20 text-rose-400 font-black"
                          : "bg-emerald-500/20 text-emerald-400 font-semibold"
                      }`}
                    >
                      {p.source_basis === "news" ? "Source news" : formatMultiple(p.baseline_ratio, p.baseline_status)}
                    </span>
                  </td>
                  <td className="py-3 px-3 font-mono">{formatPct(p.conflict_share)}</td>
                  <td className="py-3 px-3 font-mono">{p.avg_severity.toFixed(1)}</td>
                  <td className="py-3 px-3 text-right">
                    <button
                      type="button"
                      onClick={() => onSelectCountry(p.country)}
                      className="rounded-lg bg-slate-800 hover:bg-slate-700 px-3 py-1 text-xs font-bold text-emerald-400 transition-all cursor-pointer"
                    >
                      Inspect Dossier
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Main Macro Map Page ─────────────────────────────────────────────────── */
export default function MacroMapPage() {
  const [days, setDays] = useState(7);
  const [activeLayerId, setActiveLayerId] = useState<MapLayerId>("conflict");
  const [assetLens, setAssetLens] = useState("");
  const [projectionMode, setProjectionMode] = useState<"globe" | "mercator">("globe");
  const [colorblindMode, setColorblindMode] = useState(false);
  const [isListView, setIsListView] = useState(false);
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);
  const [isUnlocatedOpen, setIsUnlocatedOpen] = useState(false);
  const [mapInstance, setMapInstance] = useState<MapRef | null>(null);

  // Time slider replay states
  const [dayOffset, setDayOffset] = useState(7);
  const [isPlaying, setIsPlaying] = useState(false);

  // Operator Auth status check
  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const isOperator = me?.role === "admin" || me?.role === "reviewer";

  // URL state synchronization with URI decoding
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const urlDays = params.get("days");
    if (urlDays) {
      const parsedDays = Number(urlDays);
      setDays(parsedDays);
      setDayOffset(parsedDays);
    }
    const urlLayer = params.get("layer") as MapLayerId;
    if (urlLayer && MAP_LAYERS.some((l) => l.id === urlLayer)) setActiveLayerId(urlLayer);
    const urlAsset = params.get("asset");
    if (urlAsset) setAssetLens(urlAsset);
    const urlProj = params.get("proj");
    if (urlProj === "flat") setProjectionMode("mercator");
    const urlCountry = params.get("country");
    if (urlCountry) {
      const decodedCountry = decodeURIComponent(urlCountry);
      setSelectedCountry(decodedCountry);
    }
  }, []);

  const updateUrlState = useCallback(
    (newParams: Record<string, string | number | undefined>) => {
      if (typeof window === "undefined") return;
      const url = new URL(window.location.href);
      Object.entries(newParams).forEach(([k, v]) => {
        if (v === undefined || v === "") {
          url.searchParams.delete(k);
        } else {
          url.searchParams.set(k, String(v));
        }
      });
      window.history.replaceState(null, "", url.toString());
    },
    []
  );

  const activeLayer = useMemo(
    () => MAP_LAYERS.find((l) => l.id === activeLayerId) ?? MAP_LAYERS[0],
    [activeLayerId]
  );

  // Queries
  const {
    data: heatmap,
    isLoading: isHeatmapLoading,
    isError: isHeatmapError,
    refetch: refetchHeatmap,
  } = useQuery({
    queryKey: ["events-heatmap", days, activeLayer.event_type],
    queryFn: () =>
      fetchEventHeatmap({
        days,
        event_type: activeLayer.event_type,
        limit: 180,
      }),
    staleTime: 30_000,
  });

  const { data: maritimeChokepoints = [] } = useQuery({
    queryKey: ["maritime-chokepoints"],
    queryFn: fetchMaritimeChokepoints,
    staleTime: 60_000,
  });

  const { data: unlocatedSummary } = useQuery({
    queryKey: ["unlocated-events-count"],
    queryFn: () => fetchUnlocatedEvents(5),
    staleTime: 60_000,
  });
  const { data: assetEvents = [] } = useQuery({
    queryKey: ["map-asset-events", assetLens],
    queryFn: () => fetchEvents({ status: "published", limit: 100 }),
    enabled: Boolean(assetLens),
    staleTime: 60_000,
  });

  // Filter plotted points: exclude Unknown and Global
  const plotted = useMemo(() => {
    if (!Array.isArray(heatmap)) return [];
    return heatmap.filter(
      (p): p is GlobePoint =>
        p.latitude !== undefined &&
        p.longitude !== undefined &&
        p.country !== "Unknown" &&
        p.country !== "Global"
    );
  }, [heatmap]);

  // Asset lens filtering
  const filteredPlotted = useMemo(() => {
    if (!assetLens) return plotted;
    const countries = new Set(assetEvents
      .filter((event) => event.affected_assets?.some((asset) => asset.ticker === assetLens))
      .map((event) => event.country));
    return plotted.filter((point) => countries.has(point.country));
  }, [plotted, assetLens, assetEvents]);

  const mapRef = useCallback((instance: MapRef | null) => setMapInstance(instance), []);

  const topSurges = useMemo(() => {
    return [...plotted]
      .filter((p) => p.baseline_status !== "building_baseline" && p.baseline_ratio != null)
      .sort((a, b) => (b.baseline_ratio ?? 0) - (a.baseline_ratio ?? 0))
      .slice(0, 6);
  }, [plotted]);

  const topCountries = useMemo(() => {
    return [...plotted].sort((a, b) => b.event_count - a.event_count).slice(0, 6);
  }, [plotted]);

  const flyTo = useCallback(
    (center: [number, number], zoom = 3.5) => {
      mapInstance?.flyTo({ center, zoom, speed: 0.9, essential: true });
    },
    [mapInstance]
  );

  // Autocomplete search suggestions
  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase().trim();
    const suggestions = SEARCH_SUGGESTIONS.filter((s) => s.name.toLowerCase().includes(q));
    const countryMatches = plotted
      .filter((p) => p.country.toLowerCase().includes(q))
      .map((p) => ({
        name: p.country,
        type: "country",
        coords: [p.longitude, p.latitude] as [number, number],
        zoom: 3.5,
      }));
    return [...suggestions, ...countryMatches].slice(0, 6);
  }, [searchQuery, plotted]);

  // Robust PNG Export drawing attribution watermark into composite canvas
  const handleExportPNG = useCallback(() => {
    if (!mapInstance) return;
    try {
      const glCanvas = mapInstance.getCanvas();
      const exportCanvas = document.createElement("canvas");
      exportCanvas.width = glCanvas.width;
      exportCanvas.height = glCanvas.height;
      const ctx = exportCanvas.getContext("2d");
      if (!ctx) return;

      // Draw map
      ctx.drawImage(glCanvas, 0, 0);

      // Draw watermark & branding bar
      ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
      ctx.fillRect(0, exportCanvas.height - 48, exportCanvas.width, 48);

      ctx.fillStyle = "#10b981";
      ctx.font = "bold 16px sans-serif";
      ctx.fillText("GeoAtlas Macro Intelligence", 24, exportCanvas.height - 20);

      ctx.fillStyle = "#94a3b8";
      ctx.font = "12px sans-serif";
      const meta = `${activeLayer.label} (${days}d window) · © OpenStreetMap · CartoDB · ${new Date().toISOString().slice(0, 10)}`;
      ctx.fillText(meta, 270, exportCanvas.height - 21);

      const link = document.createElement("a");
      link.download = `geoatlas-macro-globe-${new Date().toISOString().slice(0, 10)}.png`;
      link.href = exportCanvas.toDataURL("image/png");
      link.click();
    } catch (err) {
      console.error("Export PNG failed:", err);
    }
  }, [mapInstance, activeLayer.label, days]);

  // Copy share URL
  const [copiedShare, setCopiedShare] = useState(false);
  const handleShareLink = useCallback(() => {
    if (typeof window === "undefined") return;
    navigator.clipboard.writeText(window.location.href);
    setCopiedShare(true);
    setTimeout(() => setCopiedShare(false), 2000);
  }, []);

  return (
    <div className="ga-map-page min-h-screen bg-[#eef4f1] text-slate-100 font-sans selection:bg-emerald-500 selection:text-slate-950">
      <div className="mx-auto max-w-[1720px] px-4 py-6 sm:px-6">
        {/* Top Control Header */}
        <header className="mb-5 flex flex-col gap-4 rounded-[24px] bg-slate-950 p-5 shadow-sm lg:flex-row lg:items-center lg:justify-between">
          {/* Branding & Status */}
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 shadow-[0_0_20px_rgba(16,185,129,0.2)]">
              <Globe className="h-6 w-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-black tracking-tight text-white">Global activity map</h1>
                <span className="flex items-center gap-1 rounded-full bg-emerald-500/15 border border-emerald-500/40 px-2 py-0.5 text-[9px] font-black uppercase tracking-wider text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping" />
                  Live Feed
                </span>
              </div>
              <p className="mt-0.5 text-xs text-slate-400">
                See where events are concentrated and how they connect to markets and maritime routes.
              </p>
            </div>
          </div>

          {/* Quick Omnibar Search & Fly-To */}
          <div className="relative flex-1 max-w-md">
            <div className="relative flex items-center">
              <Search className="absolute left-3.5 h-4 w-4 text-slate-400" />
              <input
                type="text"
                placeholder="Search country, waterway, or ticker..."
                value={searchQuery}
                onFocus={() => setIsSearchOpen(true)}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-2xl border border-slate-800 bg-slate-900/90 py-2.5 pl-10 pr-4 text-xs font-medium text-white placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 transition-all shadow-inner"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="absolute right-3 text-slate-400 hover:text-white text-xs cursor-pointer"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Autocomplete Dropdown */}
            {isSearchOpen && searchResults.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-2 z-50 rounded-2xl border border-slate-800 bg-slate-900 p-2 shadow-2xl space-y-1">
                {searchResults.map((item) => (
                  <button
                    key={item.name}
                    type="button"
                    onClick={() => {
                      flyTo(item.coords, item.zoom);
                      if (item.type === "country") setSelectedCountry(item.name);
                      setIsSearchOpen(false);
                      setSearchQuery("");
                    }}
                    className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-left text-xs font-semibold text-slate-200 hover:bg-slate-800 transition-all cursor-pointer"
                  >
                    <div className="flex items-center gap-2">
                      {item.type === "chokepoint" || item.type === "waterway" ? (
                        <Anchor className="h-3.5 w-3.5 text-cyan-400" />
                      ) : (
                        <MapPin className="h-3.5 w-3.5 text-emerald-400" />
                      )}
                      <span>{item.name}</span>
                    </div>
                    <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">
                      {item.type}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Action Tools */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Accessible List View / Globe Toggle */}
            <button
              type="button"
              onClick={() => setIsListView((v) => !v)}
              className={`flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-xs font-bold transition-all cursor-pointer ${
                isListView
                  ? "border-emerald-500 bg-emerald-500/20 text-emerald-300"
                  : "border-slate-800 bg-slate-900 hover:bg-slate-800 text-slate-300"
              }`}
              title="Toggle accessible tabular list view"
            >
              <List className="h-3.5 w-3.5 text-emerald-400" />
              <span>{isListView ? "Globe View" : "List View"}</span>
            </button>

            {/* Unlocated / Global Events Chip */}
            <button
              type="button"
              onClick={() => setIsUnlocatedOpen(true)}
              className="flex items-center gap-1.5 rounded-full border border-cyan-500/30 bg-cyan-950/30 hover:bg-cyan-900/40 px-3.5 py-1.5 text-xs font-bold text-cyan-300 transition-all shadow-sm cursor-pointer"
              title="Articles that lack a specific sovereign territory tag or discuss broad multi-country macro themes (e.g. global commodities, international summits, multilateral agreements)."
            >
              <Compass className="h-3.5 w-3.5 text-cyan-400" />
              <span>Unlocated &amp; Global ({unlocatedSummary?.total_unlocated ?? 135})</span>
            </button>

            {/* 3D Globe vs 2D Flat Toggle */}
            <button
              type="button"
              onClick={() => {
                const next = projectionMode === "globe" ? "mercator" : "globe";
                setProjectionMode(next);
                updateUrlState({ proj: next === "mercator" ? "flat" : undefined });
              }}
              className="flex items-center gap-1.5 rounded-full border border-slate-800 bg-slate-900 hover:bg-slate-800 px-3.5 py-1.5 text-xs font-bold text-slate-300 transition-all cursor-pointer"
              title="Toggle between 3D Globe and 2D Mercator Projection"
            >
              <Globe2 className="h-3.5 w-3.5 text-emerald-400" />
              <span>{projectionMode === "globe" ? "3D Globe" : "2D Flat"}</span>
            </button>

            {/* Export PNG */}
            <button
              type="button"
              onClick={handleExportPNG}
              className="flex items-center gap-1 rounded-full border border-slate-800 bg-slate-900 hover:bg-slate-800 p-2 text-slate-300 hover:text-white transition-all cursor-pointer"
              title="Download Snapshot as PNG (includes attribution)"
            >
              <Download className="h-4 w-4" />
            </button>

            {/* Share Map State */}
            <button
              type="button"
              onClick={handleShareLink}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-bold transition-all cursor-pointer ${
                copiedShare
                  ? "border-emerald-500 bg-emerald-500/20 text-emerald-300"
                  : "border-slate-800 bg-slate-900 hover:bg-slate-800 text-slate-300"
              }`}
              title="Copy shareable URL link"
            >
              {copiedShare ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Share2 className="h-3.5 w-3.5" />}
              <span>{copiedShare ? "Copied!" : "Share"}</span>
            </button>

            {/* Operator Review Link: STRICTLY GATED TO ADMIN / REVIEWER */}
            {isOperator && (
              <a
                href="/review"
                className="flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-950/30 hover:bg-emerald-900/40 px-3 py-1.5 text-[11px] font-bold text-emerald-300 transition-all"
                title="Access internal review queue & NLP latency telemetry"
              >
                <span>Operator QA</span>
                <ChevronRight className="h-3 w-3 text-emerald-400" />
              </a>
            )}
          </div>
        </header>

        {/* Secondary Control Ribbon: Time Window, Layers & Asset Filter */}
        <button type="button" className="ga-map-filter-toggle" aria-controls="ga-map-ribbon" aria-expanded={showMobileFilters} onClick={() => setShowMobileFilters((open) => !open)}>{showMobileFilters ? "Hide map filters" : "Filters, layers & time range"}<ChevronRight size={16} /></button>
        <div id="ga-map-ribbon" className={`ga-map-ribbon ${showMobileFilters ? "is-open" : ""} mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between bg-slate-900/60 border border-slate-800/80 rounded-2xl p-3`}>
          {/* Time Window Pills */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mr-1">Lookback:</span>
            {[7, 14, 30].map((w) => (
              <button
                key={w}
                type="button"
                onClick={() => {
                  setDays(w);
                  setDayOffset(w);
                  updateUrlState({ days: w });
                }}
                className={`rounded-full px-3 py-1 text-xs font-bold transition-all cursor-pointer ${
                  days === w
                    ? "bg-emerald-500 text-slate-950 font-black shadow-[0_0_12px_rgba(16,185,129,0.4)]"
                    : "text-slate-400 hover:bg-slate-800 hover:text-white"
                }`}
              >
                {w}d
              </button>
            ))}
          </div>

          {/* Layer Selector */}
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mr-1">Map Layer:</span>
            {MAP_LAYERS.map((layer) => (
              <button
                key={layer.id}
                type="button"
                onClick={() => {
                  setActiveLayerId(layer.id);
                  updateUrlState({ layer: layer.id });
                }}
                className={`rounded-full px-3 py-1 text-xs font-bold transition-all cursor-pointer ${
                  activeLayerId === layer.id
                    ? "bg-slate-100 text-slate-950 font-black shadow-md"
                    : "border border-slate-800 bg-slate-900/80 text-slate-400 hover:bg-slate-800 hover:text-white"
                }`}
              >
                {layer.label}
              </button>
            ))}
          </div>

          {/* Asset-First Lens Filter */}
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mr-1">Asset Lens:</span>
            {ASSET_LENSES.map((al) => (
              <button
                key={al.ticker}
                type="button"
                onClick={() => {
                  setAssetLens(al.ticker);
                  updateUrlState({ asset: al.ticker || undefined });
                }}
                className={`rounded-full px-2.5 py-1 text-xs font-bold transition-all flex items-center gap-1 cursor-pointer ${
                  assetLens === al.ticker
                    ? "bg-amber-400 text-slate-950 font-black shadow-[0_0_10px_rgba(251,191,36,0.4)]"
                    : "border border-slate-800 bg-slate-900/80 text-slate-400 hover:bg-slate-800 hover:text-white"
                }`}
              >
                <span>{al.icon}</span>
                <span>{al.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Main Grid: Globe on Left, Tactical Intelligence Panels on Right */}
        <div className="grid gap-6 lg:grid-cols-[1.65fr_1fr] items-start">
          {/* Globe Viewport Box: Sticky on desktop so it never disappears while browsing panels */}
          <div className="lg:sticky lg:top-20 relative overflow-hidden rounded-[30px] border border-slate-800 bg-slate-950 shadow-2xl flex flex-col">
            {/* Viewport Top Bar */}
            <div className="relative z-20 flex items-center justify-between border-b border-slate-800 bg-slate-950/90 backdrop-blur-md px-5 py-3">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-black uppercase tracking-[0.25em] text-emerald-400">
                  GEOPOLITICAL RADAR
                </span>
                <span className="text-slate-600">/</span>
                <span className="text-xs font-bold text-slate-300">
                  {filteredPlotted.length} countries with activity
                </span>
                {assetLens && (
                  <span className="rounded bg-amber-400/20 border border-amber-400/40 px-2 py-0.5 text-[10px] font-black text-amber-300">
                    Rule-Grounded Lens: ${assetLens}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[10px] uppercase font-bold text-slate-400">
                  {maritimeChokepoints.length} maritime corridors
                </span>
              </div>
            </div>

            {/* Viewport Body: List View or Globe View */}
            {isListView ? (
              <AccessibleListView
                points={filteredPlotted}
                onSelectCountry={(c) => {
                  setSelectedCountry(c);
                  updateUrlState({ country: c });
                }}
              />
            ) : (
              <div className="relative h-[470px] sm:h-[570px] lg:h-[calc(100vh-220px)] lg:min-h-[580px] max-h-[840px] w-full">
                {isHeatmapError ? (
                  <MapFailureState onRetry={() => refetchHeatmap()} />
                ) : isHeatmapLoading && !mapInstance ? (
                  <SkeletonGlobe />
                ) : (
                  <>
                    <MapComponent
                      ref={mapRef}
                      theme="dark"
                      center={[15, 20]}
                      zoom={1.55}
                      minZoom={0.8}
                      maxZoom={6.5}
                      renderWorldCopies={false}
                      projection={{ type: projectionMode } as any}
                    >
                      <MapControls position="bottom-right" showZoom showFullscreen />

                      {/* Layers */}
                      <HeatmapGlowLayer points={filteredPlotted} />
                      <CountryChoroplethLayer
                        points={filteredPlotted}
                        activeLayer={activeLayerId}
                        colorblindMode={colorblindMode}
                        selectedCountry={selectedCountry}
                        onSelectCountry={(c) => {
                          setSelectedCountry(c);
                          updateUrlState({ country: c });
                        }}
                      />

                      {/* Hotspot Markers */}
                      {filteredPlotted.map((p) => (
                        <HotspotDot
                          key={p.country}
                          point={p}
                          onClick={(pt) => {
                            setSelectedCountry(pt.country);
                            updateUrlState({ country: pt.country });
                          }}
                        />
                      ))}

                      {/* Maritime Chokepoints with Anchored Location Matching */}
                      {maritimeChokepoints.map((cp) => (
                        <ChokepointMarker
                          key={cp.id}
                          chokepoint={cp}
                          onClick={(c) => flyTo(c.coordinates, 4.8)}
                        />
                      ))}
                    </MapComponent>

                    {/* Dynamic Layer Legend */}
                    <LegendOverlay
                      layer={activeLayer}
                      colorblind={colorblindMode}
                      onToggleColorblind={() => setColorblindMode((v) => !v)}
                    />

                  </>
                )}
              </div>
            )}

            {/* Bottom Status Ribbon with Legal Credits */}
            <div className="relative z-20 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 bg-slate-950/90 backdrop-blur-md px-5 py-2.5 text-[11px] text-slate-500 font-medium">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-emerald-400">MapLibre GL</span>
                <span>·</span>
                <span>CartoDB Dark Basemap</span>
                <span>·</span>
                <span>Natural Earth Vector Polygons</span>
              </div>
              <div className="flex items-center gap-2">
                <span>© OpenStreetMap contributors</span>
                <span>·</span>
                <span className="text-slate-400">GeoAtlas Intelligence Engine v2.1</span>
              </div>
            </div>
          </div>

          {/* Tactical Intelligence Sidebar: Scrollable on desktop */}
          <div className="space-y-4 lg:max-h-[calc(100vh-140px)] lg:overflow-y-auto lg:pr-1.5 pb-8">
            {/* Maritime Chokepoints Live Status Watch */}
            <div className="rounded-[28px] border border-slate-800 bg-slate-900/80 p-5 shadow-xl backdrop-blur-sm">
              <div className="flex items-center justify-between mb-3.5 border-b border-slate-800 pb-2.5">
                <div className="flex items-center gap-2">
                  <Anchor className="h-4 w-4 text-cyan-400" />
                  <h2 className="text-xs font-black uppercase tracking-wider text-white">
                    Maritime Chokepoint Risk
                  </h2>
                </div>
                <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">
                  Strategic Straits
                </span>
              </div>

              <div className="space-y-2">
                {maritimeChokepoints.map((cp) => {
                  const statusBg =
                    cp.status === "disrupted"
                      ? "border-rose-500/40 bg-rose-950/30 text-rose-300"
                      : cp.status === "elevated"
                      ? "border-amber-500/40 bg-amber-950/30 text-amber-300"
                      : "border-slate-800 bg-slate-900/60 text-slate-300 hover:bg-slate-800/80";

                  const badgeBg =
                    cp.status === "disrupted"
                      ? "bg-rose-500 text-slate-950"
                      : cp.status === "elevated"
                      ? "bg-amber-400 text-slate-950"
                      : "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40";

                  return (
                    <div
                      key={cp.id}
                      className={`w-full rounded-2xl border p-3.5 transition-all ${statusBg}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => flyTo(cp.coordinates, 4.8)}
                            className="font-bold text-xs text-white hover:text-cyan-400 transition-colors text-left cursor-pointer"
                          >
                            {cp.name}
                          </button>
                          <span className="text-[10px] text-slate-400 font-mono">
                            ({cp.traffic_estimate.split("(")[0].trim()})
                          </span>
                        </div>
                        <span className={`rounded-md px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider ${badgeBg}`}>
                          {cp.status}
                        </span>
                      </div>

                      {/* Traffic Metric & Source Citation */}
                      <div className="mt-2 space-y-1">
                        <p className="text-[11px] text-slate-300 font-medium leading-relaxed">
                          {cp.traffic_estimate}
                        </p>
                        <div className="flex items-center gap-1.5 text-[10px] text-slate-400 pt-0.5">
                          <span>Source:</span>
                          <a
                            href={cp.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-slate-400 hover:text-cyan-400 hover:underline inline-flex items-center gap-0.5 transition-colors font-medium"
                          >
                            <span>{cp.source_citation}</span>
                            <ExternalLink className="h-2.5 w-2.5" />
                          </a>
                        </div>
                      </div>

                      {/* Trigger headlines or latest news */}
                      <div className="mt-2 pt-2 border-t border-slate-800/80 space-y-1">
                        <p className="text-[9px] uppercase tracking-wider text-slate-400 font-bold">
                          {cp.trigger_headlines.length > 0 ? "Triggering Incidents:" : "Latest Headline:"}
                        </p>
                        {cp.trigger_headlines.length > 0 ? (
                          cp.trigger_headlines.map((hl, i) => (
                            <p key={i} className="text-[11px] text-slate-200 line-clamp-2 leading-snug">
                              • {hl}
                            </p>
                          ))
                        ) : (
                          <p className="text-[11px] text-slate-400 line-clamp-1 italic">
                            {cp.latest_headline ?? cp.note}
                          </p>
                        )}
                      </div>

                      {cp.top_assets.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {cp.top_assets.map((ticker) => (
                            <span key={ticker} className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] font-bold text-amber-300 font-mono">
                              ${formatDisplayTicker(ticker)}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* High Relative Surge Hotspots */}
            <div className="rounded-[28px] border border-slate-800 bg-slate-900/80 p-5 shadow-xl backdrop-blur-sm">
              <div className="flex items-center justify-between mb-3.5 border-b border-slate-800 pb-2.5">
                <div className="flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-rose-500" />
                  <h2
                    className="text-xs font-black uppercase tracking-wider text-white"
                    title="Non-overlapping baseline surge velocity: compares current event rate against prior 30-day baseline (smoothed, n ≥ 3)"
                  >
                    Where activity is rising
                  </h2>
                </div>
                <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">
                  Smoothed (n ≥ 3)
                </span>
              </div>

              <div className="space-y-2">
                {topSurges.length === 0 ? (
                  <p className="text-xs text-slate-500">
                    No verified surges detected (countries with n &lt; 3 marked as building baseline).
                  </p>
                ) : (
                  topSurges.map((r) => (
                    <button
                      key={r.country}
                      type="button"
                      onClick={() => {
                        flyTo([r.longitude, r.latitude], 3.8);
                        setSelectedCountry(r.country);
                        updateUrlState({ country: r.country });
                      }}
                      className="w-full flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/60 hover:bg-slate-800/80 p-3 text-left transition-all cursor-pointer"
                    >
                      <div>
                        <p className="font-bold text-xs text-white">{r.country}</p>
                        <p className="mt-0.5 text-[10px] text-slate-400">
                          {r.event_count} {r.source_basis === "news" ? "articles" : "events"} · sev {r.avg_severity.toFixed(1)} · conflict {formatPct(r.conflict_share)}
                        </p>
                      </div>
                      <div className="text-right">
                        <span className="rounded-lg bg-rose-500/20 border border-rose-500/40 px-2 py-0.5 text-xs font-black text-rose-400">
                          {formatMultiple(r.baseline_ratio, r.baseline_status)}
                        </span>
                        <p className="text-[8px] uppercase tracking-wider text-slate-500 mt-0.5 font-bold">vs prior 30d base</p>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>

            {/* Sovereign Event Volumes */}
            <div className="rounded-[28px] border border-slate-800 bg-slate-900/80 p-5 shadow-xl backdrop-blur-sm">
              <div className="flex items-center justify-between mb-3.5 border-b border-slate-800 pb-2.5">
                <div className="flex items-center gap-2">
                  <Globe2 className="h-4 w-4 text-emerald-400" />
                  <h2 className="text-xs font-black uppercase tracking-wider text-white">
                    Total Volume Leaders
                  </h2>
                </div>
                <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">
                  Event Density
                </span>
              </div>

              <div className="space-y-2">
                {topCountries.map((r) => (
                  <button
                    key={r.country}
                    type="button"
                    onClick={() => {
                      flyTo([r.longitude, r.latitude], 3.8);
                      setSelectedCountry(r.country);
                      updateUrlState({ country: r.country });
                    }}
                    className="w-full flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/60 hover:bg-slate-800/80 p-3 text-left transition-all cursor-pointer"
                  >
                    <div>
                      <p className="font-bold text-xs text-white">{r.country}</p>
                      <p className="mt-0.5 text-[10px] text-slate-400">
                        sev {r.avg_severity.toFixed(1)} · conf {formatPct(r.avg_confidence)}
                      </p>
                    </div>
                    <span className="rounded-lg bg-emerald-500/20 border border-emerald-500/40 px-2 py-0.5 text-xs font-black text-emerald-400">
                      {r.event_count} {r.source_basis === "news" ? "articles" : "events"}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Country Intelligence Slide-Over Drawer (Responsive Bottom Sheet on Mobile) */}
      {selectedCountry && (
        <CountryIntelligenceDrawer
          country={selectedCountry}
          point={plotted.find((p) => p.country.toLowerCase() === selectedCountry.toLowerCase())}
          onClose={() => {
            setSelectedCountry(null);
            updateUrlState({ country: undefined });
          }}
          onFlyTo={(coords) => flyTo(coords, 4.0)}
        />
      )}

      {/* Unlocated & Global Events Slide-Over Drawer */}
      <UnlocatedEventsDrawer
        isOpen={isUnlocatedOpen}
        onClose={() => setIsUnlocatedOpen(false)}
      />
    </div>
  );
}
