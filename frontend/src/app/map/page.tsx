"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Anchor, Globe2, Radar, Waves } from "lucide-react";
import type { GeoJSONSource } from "maplibre-gl";

import { fetchEventHeatmap, fetchQualitySummary, type EventHeatmapPoint } from "@/lib/api";
import {
  Map as MapComponent,
  useMap,
  MapMarker,
  MarkerContent,
  MarkerTooltip,
  MapControls,
  type MapRef,
} from "@/components/ui/map";

/* ─── Constants ───────────────────────────────────────────────────────────── */
const EVENT_TYPE_FILTERS = [
  { value: "", label: "All Events" },
  { value: "conflict", label: "Conflict" },
  { value: "sanction", label: "Sanctions" },
  { value: "trade_policy", label: "Trade Policy" },
  { value: "energy_disruption", label: "Energy" },
  { value: "economic_data", label: "Economic Data" },
  { value: "election", label: "Elections" },
  { value: "regulation", label: "Regulation" },
] as const;

const MARITIME_CHOKEPOINTS = [
  { id: "hormuz", name: "Strait of Hormuz", coordinates: [56.25, 26.55] as [number, number], note: "Persian Gulf oil and LNG exit route.", relatedCountries: ["Iran", "United Arab Emirates", "Qatar", "Saudi Arabia", "Oman"] },
  { id: "bab-el-mandeb", name: "Bab el-Mandeb", coordinates: [43.35, 12.6] as [number, number], note: "Red Sea to Gulf of Aden gateway.", relatedCountries: ["Yemen", "Djibouti", "Saudi Arabia", "Egypt"] },
  { id: "suez", name: "Suez Canal", coordinates: [32.35, 30.7] as [number, number], note: "Mediterranean to Red Sea canal corridor.", relatedCountries: ["Egypt", "Israel", "Saudi Arabia"] },
  { id: "malacca", name: "Strait of Malacca", coordinates: [100.95, 3.2] as [number, number], note: "Asia-Europe container and energy artery.", relatedCountries: ["Singapore", "Malaysia", "Indonesia", "China", "India"] },
  { id: "bosporus", name: "Bosporus", coordinates: [29.05, 41.08] as [number, number], note: "Black Sea maritime gateway.", relatedCountries: ["Turkey", "Russia", "Ukraine"] },
  { id: "gibraltar", name: "Strait of Gibraltar", coordinates: [-5.45, 35.95] as [number, number], note: "Atlantic entrance to the Mediterranean.", relatedCountries: ["Spain", "Morocco", "United Kingdom"] },
  { id: "panama", name: "Panama Canal", coordinates: [-79.55, 9.08] as [number, number], note: "Atlantic-Pacific shipping transit.", relatedCountries: ["Panama", "United States", "China"] },
] as const;

/* ─── Types ───────────────────────────────────────────────────────────────── */
type GlobePoint = EventHeatmapPoint & { latitude: number; longitude: number };

/* ─── Helpers ─────────────────────────────────────────────────────────────── */
function formatPct(v?: number) { return v == null ? "-" : `${(v * 100).toFixed(1)}%`; }
function formatNum(v?: number, d = 1) { return v == null ? "-" : v.toFixed(d); }

function hotspotColor(conflictShare: number, eventCount: number) {
  const heat = Math.min(1, conflictShare * 0.55 + Math.min(eventCount / 15, 1) * 0.45);
  if (heat >= 0.65) return "#f04e5e";
  if (heat >= 0.35) return "#e6a832";
  return "#10b981";
}

/* ─── Country Choropleth Layer ────────────────────────────────────────────── */
function CountryChoroplethLayer({ points }: { points: GlobePoint[] }) {
  const { map, isLoaded } = useMap();
  const id = useId();
  const sourceId = `countries-${id}`;
  const fillId = `countries-fill-${id}`;
  const lineId = `countries-line-${id}`;

  const byCountry = useMemo(() => {
    const m = new globalThis.Map<string, GlobePoint>();
    points.forEach((p) => m.set(p.country, p));
    return m;
  }, [points]);

  useEffect(() => {
    if (!map || !isLoaded) return;
    let cancelled = false;

    async function load() {
      const resp = await fetch("/map-data/countries.geo.json");
      const raw = await resp.json();
      if (cancelled || !map) return;

      const enriched = {
        ...raw,
        features: raw.features.map((f: any) => {
          const name = String(f.properties?.name ?? "");
          const heat = byCountry.get(name);
          const heatValue = heat
            ? Math.min(1, heat.conflict_share * 0.55 + Math.min(heat.event_count / 10, 1) * 0.45)
            : 0;
          return { ...f, properties: { ...f.properties, heat_value: heatValue } };
        }),
      };

      if (map.getSource(sourceId)) return;
      map.addSource(sourceId, { type: "geojson", data: enriched });

      map.addLayer({
        id: fillId, type: "fill", source: sourceId,
        paint: {
          "fill-color": ["interpolate", ["linear"], ["get", "heat_value"],
            0, "#064e3b", 0.35, "#10b981", 0.65, "#d97706", 1, "#f04e5e"],
          "fill-opacity": 0.75,
        },
      }, map.getLayer("hotspot-heat") ? "hotspot-heat" : undefined);

      map.addLayer({
        id: lineId, type: "line", source: sourceId,
        paint: {
          "line-color": "rgba(52,211,153,0.5)",
          "line-width": ["interpolate", ["linear"], ["zoom"], 0, 0.5, 4, 1.2],
        },
      });
    }
    load();
    return () => {
      cancelled = true;
      try {
        if (map.getLayer(lineId)) map.removeLayer(lineId);
        if (map.getLayer(fillId)) map.removeLayer(fillId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
      } catch { /* ignore */ }
    };
  }, [map, isLoaded, byCountry, sourceId, fillId, lineId]);

  return null;
}

/* ─── Heatmap Glow Layer ──────────────────────────────────────────────────── */
function HeatmapGlowLayer({ points }: { points: GlobePoint[] }) {
  const { map, isLoaded } = useMap();
  const id = useId();
  const sourceId = `heat-src-${id}`;
  const layerId = `hotspot-heat`;

  const geoJson = useMemo(() => ({
    type: "FeatureCollection" as const,
    features: points.map((p) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [p.longitude, p.latitude] },
      properties: { event_count: p.event_count, conflict_share: p.conflict_share },
    })),
  }), [points]);

  useEffect(() => {
    if (!map || !isLoaded) return;
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: "geojson", data: geoJson });
    }
    if (!map.getLayer(layerId)) {
      map.addLayer({
        id: layerId, type: "heatmap", source: sourceId, maxzoom: 8,
        paint: {
          "heatmap-weight": ["interpolate", ["linear"], ["get", "event_count"], 1, 0.15, 20, 1],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 0.3, 4, 1],
          "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"],
            0, "rgba(16,185,129,0)", 0.25, "rgba(16,185,129,0.35)",
            0.5, "rgba(217,119,6,0.55)", 0.75, "rgba(240,78,94,0.7)", 1, "rgba(240,78,94,0.9)"],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 14, 4, 30],
          "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 0, 0.6, 6, 0.3],
        },
      });
    }
    return () => {
      try {
        if (map.getLayer(layerId)) map.removeLayer(layerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
      } catch { /* ignore */ }
    };
  }, [map, isLoaded, sourceId, layerId, geoJson]);

  return null;
}

/* ─── Hotspot Marker ──────────────────────────────────────────────────────── */
function HotspotDot({ point }: { point: GlobePoint }) {
  const color = hotspotColor(point.conflict_share, point.event_count);
  const sz = Math.max(10, Math.min(22, point.event_count * 1.5));

  return (
    <MapMarker longitude={point.longitude} latitude={point.latitude}>
      <MarkerContent>
        <div className="relative flex items-center justify-center" style={{ width: sz * 2.4, height: sz * 2.4 }}>
          <div className="absolute inset-0 animate-ping rounded-full opacity-15" style={{ backgroundColor: color, animationDuration: "3.5s" }} />
          <div className="absolute rounded-full opacity-20" style={{ backgroundColor: color, width: sz * 1.3, height: sz * 1.3 }} />
          <div className="relative rounded-full border border-white/60" style={{ backgroundColor: color, width: Math.max(7, sz * 0.45), height: Math.max(7, sz * 0.45), boxShadow: `0 0 10px ${color}80` }} />
        </div>
      </MarkerContent>
      <MarkerTooltip offset={18} className="bg-white border border-gray-200 text-gray-900 shadow-md">
        <p className="font-bold text-gray-900">{point.country}</p>
        <p className="mt-0.5 text-[10px] text-gray-500 font-medium">
          {point.event_count} events · sev {point.avg_severity.toFixed(1)} · conflict {(point.conflict_share * 100).toFixed(0)}%
        </p>
      </MarkerTooltip>
    </MapMarker>
  );
}

/* ─── Maritime Chokepoint Marker ──────────────────────────────────────────── */
function ChokepointDot({ name, coordinates, note, active }: { name: string; coordinates: [number, number]; note: string; active: boolean }) {
  return (
    <MapMarker longitude={coordinates[0]} latitude={coordinates[1]}>
      <MarkerContent>
        <div className={`h-3 w-3 rounded-full border ${active ? "border-amber-300 bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]" : "border-gray-400 bg-gray-500"}`} />
      </MarkerContent>
      <MarkerTooltip offset={14} className="bg-white border border-gray-200 text-gray-900 shadow-md">
        <p className="font-bold text-amber-700">{name}</p>
        <p className="mt-0.5 text-[10px] text-gray-500 font-medium">{note}</p>
      </MarkerTooltip>
    </MapMarker>
  );
}

/* ─── Globe Wrapper ───────────────────────────────────────────────────────── */
function MapGlobe({ points, mapRef, onMapRef }: { points: GlobePoint[]; mapRef: MapRef | null; onMapRef: (ref: MapRef | null) => void }) {
  const maritimeRows = useMemo(() => {
    const activeCountries = new Set(points.map((p) => p.country));
    return MARITIME_CHOKEPOINTS.map((r) => ({
      ...r,
      active: r.relatedCountries.some((c) => activeCountries.has(c)),
    }));
  }, [points]);

  return (
    <div className="overflow-hidden rounded-[24px] border border-gray-200 bg-gray-900 shadow-sm relative">
      <div className="relative z-20 flex items-center justify-between border-b border-gray-800 bg-gray-900/90 backdrop-blur-sm px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-bold uppercase tracking-[0.3em] text-emerald-400">Terravox</span>
          <span className="text-[10px] uppercase tracking-[0.2em] text-gray-400 font-semibold">mapcn globe</span>
        </div>
        <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-rose-400">Countries: {points.length}</div>
      </div>

      <div className="relative h-[620px]">
        <MapComponent
          ref={(ref) => onMapRef(ref)}
          theme="dark"
          center={[12, 18]}
          zoom={1.4}
          minZoom={0.8}
          maxZoom={5.5}
          renderWorldCopies={false}
          projection={{ type: "globe" } as any}
        >
          <MapControls position="bottom-right" showZoom showFullscreen />
          <HeatmapGlowLayer points={points} />
          <CountryChoroplethLayer points={points} />
          {points.map((p) => <HotspotDot key={p.country} point={p} />)}
          {maritimeRows.map((r) => (
            <ChokepointDot key={r.id} name={r.name} coordinates={[...r.coordinates] as [number, number]} note={r.note} active={r.active} />
          ))}
        </MapComponent>
      </div>

      <div className="relative z-20 flex flex-wrap items-center justify-between gap-2 border-t border-gray-800 bg-gray-900/90 backdrop-blur-sm px-4 py-3 text-[10px] uppercase tracking-[0.2em] text-gray-400 font-medium">
        <span>MapLibre Globe</span>
        <span className="text-emerald-400 font-semibold">Drag to rotate · Wheel to zoom</span>
        <span>mapcn powered</span>
      </div>
    </div>
  );
}

/* ─── Sidebar Panels ──────────────────────────────────────────────────────── */
function SidebarCard({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-[24px] border border-gray-200 bg-white p-5 shadow-sm ${className ?? ""}`}>{children}</div>;
}

function SidebarTitle({ icon: Icon, label, color }: { icon: typeof Globe2; label: string; color: string }) {
  return (
    <div className="mb-3.5 flex items-center gap-2">
      <Icon className="h-4 w-4" style={{ color }} />
      <h2 className="text-xs font-bold uppercase tracking-wider text-gray-900">{label}</h2>
    </div>
  );
}

/* ─── Main Page ───────────────────────────────────────────────────────────── */
export default function MacroMapPage() {
  const [days, setDays] = useState(14);
  const [eventType, setEventType] = useState("");
  const [mapInstance, setMapInstance] = useState<MapRef | null>(null);

  const { data: heatmap, isLoading } = useQuery({
    queryKey: ["events-heatmap", days, eventType],
    queryFn: () => fetchEventHeatmap({ days, event_type: eventType || undefined, limit: 180 }),
    staleTime: 30_000,
  });
  const { data: quality } = useQuery({
    queryKey: ["events-quality-summary"],
    queryFn: fetchQualitySummary,
    staleTime: 60_000,
  });

  const plotted = useMemo(() => (heatmap ?? []).filter((p): p is GlobePoint => p.latitude !== undefined && p.longitude !== undefined), [heatmap]);
  const topCountries = useMemo(() => [...plotted].sort((a, b) => b.event_count - a.event_count).slice(0, 10), [plotted]);
  const topConflict = useMemo(() => {
    if (eventType && eventType !== "conflict") {
      return [...plotted].sort((a, b) => b.event_count * b.avg_severity - a.event_count * a.avg_severity).slice(0, 6);
    }
    return [...plotted].sort((a, b) => b.conflict_share * b.event_count - a.conflict_share * a.event_count).slice(0, 6);
  }, [plotted, eventType]);

  const hotspotTitle = useMemo(() => {
    if (!eventType) return "Conflict Hotspots";
    const found = EVENT_TYPE_FILTERS.find((f) => f.value === eventType);
    return `${found?.label ?? eventType} Hotspots`;
  }, [eventType]);

  const maritimeRows = useMemo(() => {
    const active = new Set(plotted.map((r) => r.country));
    return MARITIME_CHOKEPOINTS.map((r) => ({ ...r, active: r.relatedCountries.some((c) => active.has(c)) }));
  }, [plotted]);

  const flyTo = useCallback((center: [number, number], zoom: number) => {
    mapInstance?.flyTo({ center, zoom, speed: 0.8, essential: true });
  }, [mapInstance]);

  return (
    <div className="min-h-screen bg-[#f8fafc] px-4 py-8 text-gray-900">
      <div className="mx-auto max-w-[1680px]">
        {/* Header */}
        <div className="mb-6 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Globe2 className="h-5 w-5 text-emerald-600" />
              <h1 className="text-2xl font-bold tracking-tight text-gray-900">Macro Globe</h1>
            </div>
            <p className="mt-1.5 max-w-3xl text-sm text-gray-500">Interactive MapLibre globe powered by mapcn — heat-filled countries, heatmap layers, maritime chokepoints, and hotspot markers.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-full border border-gray-200 bg-white p-1 shadow-sm">
              {[7, 14, 30].map((w) => (
                <button
                  key={w}
                  onClick={() => setDays(w)}
                  className={`rounded-full px-3 py-1.5 text-xs font-bold transition-all ${
                    days === w ? "bg-gray-900 text-white shadow-sm" : "text-gray-600 hover:bg-gray-100"
                  }`}
                >
                  {w}d
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {EVENT_TYPE_FILTERS.map((o) => (
                <button
                  key={o.value}
                  onClick={() => setEventType(o.value)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-all ${
                    eventType === o.value
                      ? "border-emerald-600 bg-emerald-600 text-white shadow-sm"
                      : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50 shadow-sm"
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Metrics row */}
        <div className="mb-6 grid gap-4 md:grid-cols-3">
          <MetricCard label="Classification Accuracy" value={formatPct(quality?.classification_accuracy)} hint="Approve / Reject agreement proxy" />
          <MetricCard label="NLP Latency P95" value={quality?.nlp_latency_p95_seconds != null ? `${quality.nlp_latency_p95_seconds.toFixed(1)}s` : "-"} hint="Article create to NLP processed" />
          <MetricCard label="Review Backlog" value={`${quality?.review_queue_backlog ?? 0}`} hint="Pending human review events" />
        </div>

        {/* Globe + Sidebar */}
        <div className="grid gap-6 2xl:grid-cols-[1.7fr_0.95fr]">
          <div className="rounded-[30px] border border-gray-200 bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <p className="text-xs font-bold uppercase tracking-wider text-gray-900">World Event Globe</p>
                <p className="mt-0.5 text-xs text-gray-500">{isLoading ? "Loading heatmap intelligence..." : `${plotted.length} mapped countries with mapcn overlays`}</p>
              </div>
              <Radar className="h-4 w-4 text-emerald-600" />
            </div>
            <MapGlobe points={plotted} mapRef={mapInstance} onMapRef={setMapInstance} />
          </div>

          {/* Sidebar */}
          <div className="space-y-4">
            <SidebarCard>
              <SidebarTitle icon={AlertTriangle} label={hotspotTitle} color="#e11d48" />
              <div className="space-y-2">
                {topConflict.length === 0 ? (
                  <p className="text-xs text-gray-400">No hotspots in this time window.</p>
                ) : (
                  topConflict.map((r) => (
                    <button
                      key={r.country}
                      onClick={() => flyTo([r.longitude, r.latitude], 2.5)}
                      className="block w-full rounded-xl border border-gray-100 bg-gray-50 hover:bg-gray-100 hover:border-gray-200 px-3.5 py-2.5 text-left transition-all"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate text-sm font-bold text-gray-900">{r.country}</p>
                        <p className="text-xs font-bold text-rose-600">
                          {r.conflict_share > 0 ? formatPct(r.conflict_share) : `${r.event_count} events`}
                        </p>
                      </div>
                      <p className="mt-1 text-xs text-gray-500">
                        {r.event_count} events · sev {formatNum(r.avg_severity, 2)} · conf {formatNum(r.avg_confidence, 2)}
                      </p>
                    </button>
                  ))
                )}
              </div>
            </SidebarCard>

            <SidebarCard>
              <SidebarTitle icon={Globe2} label="Country Highlights" color="#059669" />
              <div className="space-y-2">
                {topCountries.length === 0 ? (
                  <p className="text-xs text-gray-400">No country highlights yet.</p>
                ) : (
                  topCountries.map((r) => (
                    <button
                      key={r.country}
                      onClick={() => flyTo([r.longitude, r.latitude], 2.1)}
                      className="block w-full rounded-xl border border-gray-100 bg-gray-50 hover:bg-gray-100 hover:border-gray-200 px-3.5 py-2.5 text-left transition-all"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate text-sm font-bold text-gray-900">{r.country}</p>
                        <p className="text-xs font-bold text-emerald-600">{r.event_count} events</p>
                      </div>
                      <p className="mt-1 text-xs text-gray-500">
                        sev {formatNum(r.avg_severity, 2)} · conf {formatNum(r.avg_confidence, 2)} · conflict {formatPct(r.conflict_share)}
                      </p>
                    </button>
                  ))
                )}
              </div>
            </SidebarCard>

            <SidebarCard>
              <SidebarTitle icon={Anchor} label="Maritime Watch" color="#d97706" />
              <div className="space-y-2">
                {maritimeRows.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => flyTo([...r.coordinates] as [number, number], 3.4)}
                    className={`block w-full rounded-xl border px-3.5 py-2.5 text-left transition-all ${
                      r.active
                        ? "border-amber-200 bg-amber-50/70 hover:bg-amber-100/70"
                        : "border-gray-100 bg-gray-50 hover:bg-gray-100"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-bold text-gray-900">{r.name}</p>
                      <p className={`text-[10px] font-bold uppercase tracking-wider ${r.active ? "text-amber-700" : "text-gray-400"}`}>
                        {r.active ? "Active" : "Monitor"}
                      </p>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">{r.note}</p>
                  </button>
                ))}
              </div>
            </SidebarCard>

            <SidebarCard>
              <SidebarTitle icon={Waves} label="Quality Signals" color="#2563eb" />
              <div className="space-y-1 text-xs text-gray-600">
                <p>Auto-approved rate: <span className="font-bold text-gray-800">{formatPct(quality?.auto_approved_rate)}</span></p>
                <p>Asset mapping coverage: <span className="font-bold text-gray-800">{formatPct(quality?.asset_mapping_coverage)}</span></p>
                <p>Ingestion freshness: <span className="font-bold text-gray-800">{quality?.news_ingestion_freshness_minutes != null ? `${quality.news_ingestion_freshness_minutes.toFixed(1)} min` : "-"}</span></p>
              </div>
            </SidebarCard>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── MetricCard ──────────────────────────────────────────────────────────── */
function MetricCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-[22px] border border-gray-200 bg-white px-5 py-4 shadow-sm">
      <p className="text-xs font-bold uppercase tracking-wider text-gray-400">{label}</p>
      <p className="mt-1 text-2xl font-black text-gray-900 tabular-nums">{value}</p>
      <p className="mt-1 text-xs text-gray-500">{hint}</p>
    </div>
  );
}
