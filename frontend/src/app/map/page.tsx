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
  return "#20a07f";
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
            0, "#144f42", 0.35, "#20a07f", 0.65, "#c0b53b", 1, "#f04e5e"],
          "fill-opacity": 0.75,
        },
      }, map.getLayer("hotspot-heat") ? "hotspot-heat" : undefined);

      map.addLayer({
        id: lineId, type: "line", source: sourceId,
        paint: {
          "line-color": "rgba(123,255,228,0.45)",
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
            0, "rgba(32,160,127,0)", 0.25, "rgba(32,160,127,0.35)",
            0.5, "rgba(230,168,50,0.55)", 0.75, "rgba(240,78,94,0.7)", 1, "rgba(240,78,94,0.9)"],
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
          <div className="relative rounded-full border border-white/40" style={{ backgroundColor: color, width: Math.max(7, sz * 0.45), height: Math.max(7, sz * 0.45), boxShadow: `0 0 10px ${color}80` }} />
        </div>
      </MarkerContent>
      <MarkerTooltip offset={18}>
        <p className="font-semibold text-[#e6fff8]">{point.country}</p>
        <p className="mt-0.5 text-[10px] text-[#8db8ab]">
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
        <div className={`h-3 w-3 rounded-full border ${active ? "border-[#fff1c4] bg-[#ffd36b]" : "border-[#6b7c4d] bg-[#9d8654]"}`} style={{ boxShadow: active ? "0 0 8px #ffd36b80" : "none" }} />
      </MarkerContent>
      <MarkerTooltip offset={14}>
        <p className="font-semibold text-[#ffe8b5]">{name}</p>
        <p className="mt-0.5 text-[10px] text-[#8aa397]">{note}</p>
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
    <div className="overflow-hidden rounded-[28px] border border-[#12362d] bg-[#020912] shadow-[0_24px_80px_rgba(0,0,0,0.45)]">
      <div className="pointer-events-none absolute inset-0 z-10 bg-[radial-gradient(circle_at_top,rgba(0,255,214,0.08),transparent_34%)]" />
      <div className="relative z-20 flex items-center justify-between border-b border-[#0b2720] px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-[0.34em] text-[#86ffdc]">Terravox</span>
          <span className="text-[10px] uppercase tracking-[0.26em] text-[#2a6655]">mapcn globe</span>
        </div>
        <div className="text-[10px] uppercase tracking-[0.22em] text-[#ff71af]">Countries: {points.length}</div>
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

      <div className="relative z-20 flex flex-wrap items-center justify-between gap-2 border-t border-[#0b2720] px-4 py-3 text-[10px] uppercase tracking-[0.24em]">
        <span className="text-[#315a4f]">MapLibre Globe</span>
        <span className="text-[#86ffdc]">Drag to rotate · Wheel to zoom</span>
        <span className="text-[#315a4f]">mapcn powered</span>
      </div>
    </div>
  );
}

/* ─── Sidebar Panels ──────────────────────────────────────────────────────── */
function SidebarCard({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-[24px] border border-[#11352b] bg-[#07121a] p-4 ${className ?? ""}`}>{children}</div>;
}

function SidebarTitle({ icon: Icon, label, color }: { icon: typeof Globe2; label: string; color: string }) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <Icon className="h-4 w-4" style={{ color }} />
      <h2 className="text-sm font-semibold uppercase tracking-[0.18em]" style={{ color }}>{label}</h2>
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
  const topConflict = useMemo(() => [...plotted].sort((a, b) => b.conflict_share * b.event_count - a.conflict_share * a.event_count).slice(0, 6), [plotted]);
  const maritimeRows = useMemo(() => {
    const active = new Set(plotted.map((r) => r.country));
    return MARITIME_CHOKEPOINTS.map((r) => ({ ...r, active: r.relatedCountries.some((c) => active.has(c)) }));
  }, [plotted]);

  const flyTo = useCallback((center: [number, number], zoom: number) => {
    mapInstance?.flyTo({ center, zoom, speed: 0.8, essential: true });
  }, [mapInstance]);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,#10232c_0%,#071118_34%,#03070b_100%)] px-4 py-8 text-white">
      <div className="mx-auto max-w-[1680px]">
        {/* Header */}
        <div className="mb-6 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Globe2 className="h-5 w-5 text-[#74ffd6]" />
              <h1 className="text-2xl font-semibold tracking-[0.08em] text-[#ddfff5]">Macro Globe</h1>
            </div>
            <p className="mt-2 max-w-3xl text-sm text-[#6ea394]">Interactive MapLibre globe powered by mapcn — heat-filled countries, heatmap layers, maritime chokepoints, and hotspot markers.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-full border border-[#18473a] bg-[#07121a] p-1">
              {[7, 14, 30].map((w) => (
                <button key={w} onClick={() => setDays(w)} className={`rounded-full px-3 py-1.5 text-sm font-semibold transition-colors ${days === w ? "bg-[#72ffd2] text-[#041117]" : "text-[#91bdb0] hover:bg-[#102129]"}`}>{w}d</button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {EVENT_TYPE_FILTERS.map((o) => (
                <button key={o.value} onClick={() => setEventType(o.value)} className={`rounded-full border px-3 py-1.5 text-sm font-semibold transition-colors ${eventType === o.value ? "border-[#72ffd2] bg-[#72ffd2] text-[#031118]" : "border-[#18473a] bg-[#07121a] text-[#91bdb0] hover:bg-[#102129]"}`}>{o.label}</button>
              ))}
            </div>
          </div>
        </div>

        {/* Metrics row */}
        <div className="mb-6 grid gap-3 md:grid-cols-3">
          <MetricCard label="Classification Accuracy" value={formatPct(quality?.classification_accuracy)} hint="Approve / Reject agreement proxy" />
          <MetricCard label="NLP Latency p95" value={quality?.nlp_latency_p95_seconds != null ? `${quality.nlp_latency_p95_seconds.toFixed(1)}s` : "-"} hint="Article create to NLP processed" />
          <MetricCard label="Review Backlog" value={`${quality?.review_queue_backlog ?? 0}`} hint="Pending human review events" />
        </div>

        {/* Globe + Sidebar */}
        <div className="grid gap-5 2xl:grid-cols-[1.7fr_0.95fr]">
          <div className="rounded-[30px] border border-[#11352b] bg-[linear-gradient(180deg,rgba(7,18,26,0.96),rgba(4,9,14,0.96))] p-4">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold uppercase tracking-[0.22em] text-[#79ffd7]">World Event Globe</p>
                <p className="mt-1 text-xs text-[#4d7669]">{isLoading ? "Loading heatmap intelligence..." : `${plotted.length} mapped countries with mapcn overlays`}</p>
              </div>
              <Radar className="h-4 w-4 text-[#79ffd7]" />
            </div>
            <MapGlobe points={plotted} mapRef={mapInstance} onMapRef={setMapInstance} />
          </div>

          {/* Sidebar */}
          <div className="space-y-4">
            <SidebarCard>
              <SidebarTitle icon={AlertTriangle} label="Conflict Hotspots" color="#ffd1db" />
              <div className="space-y-2">
                {topConflict.length === 0 ? <p className="text-sm text-[#6f988b]">No conflict-heavy hotspots in this time window.</p> : topConflict.map((r) => (
                  <button key={r.country} onClick={() => flyTo([r.longitude, r.latitude], 2.5)} className="block w-full rounded-xl border border-[#17372f] bg-[#08161d] px-3 py-2 text-left transition-colors hover:bg-[#0c1d26]">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-semibold text-[#f2fffb]">{r.country}</p>
                      <p className="text-xs text-[#ff9bb6]">{formatPct(r.conflict_share)}</p>
                    </div>
                    <p className="mt-1 text-xs text-[#6f988b]">{r.event_count} events · sev {formatNum(r.avg_severity, 2)} · conf {formatNum(r.avg_confidence, 2)}</p>
                  </button>
                ))}
              </div>
            </SidebarCard>

            <SidebarCard>
              <SidebarTitle icon={Globe2} label="Country Highlights" color="#79ffd7" />
              <div className="space-y-2">
                {topCountries.length === 0 ? <p className="text-sm text-[#6f988b]">No country highlights yet.</p> : topCountries.map((r) => (
                  <button key={r.country} onClick={() => flyTo([r.longitude, r.latitude], 2.1)} className="block w-full rounded-xl border border-[#17372f] bg-[#08161d] px-3 py-2 text-left transition-colors hover:bg-[#0c1d26]">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-semibold text-[#f2fffb]">{r.country}</p>
                      <p className="text-xs text-[#79ffd7]">{r.event_count} events</p>
                    </div>
                    <p className="mt-1 text-xs text-[#6f988b]">sev {formatNum(r.avg_severity, 2)} · conf {formatNum(r.avg_confidence, 2)} · conflict {formatPct(r.conflict_share)}</p>
                  </button>
                ))}
              </div>
            </SidebarCard>

            <SidebarCard>
              <SidebarTitle icon={Anchor} label="Maritime Watch" color="#ffe8b5" />
              <div className="space-y-2">
                {maritimeRows.map((r) => (
                  <button key={r.id} onClick={() => flyTo([...r.coordinates] as [number, number], 3.4)} className={`block w-full rounded-xl border px-3 py-2 text-left transition-colors ${r.active ? "border-[#5e4b16] bg-[#17140a] hover:bg-[#1d190d]" : "border-[#17372f] bg-[#08161d] hover:bg-[#0c1d26]"}`}>
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-semibold text-[#f2fffb]">{r.name}</p>
                      <p className={`text-[10px] uppercase tracking-[0.2em] ${r.active ? "text-[#ffd782]" : "text-[#5f776d]"}`}>{r.active ? "Active" : "Monitor"}</p>
                    </div>
                    <p className="mt-1 text-xs text-[#8aa397]">{r.note}</p>
                  </button>
                ))}
              </div>
            </SidebarCard>

            <SidebarCard>
              <SidebarTitle icon={Waves} label="Quality Signals" color="#cde7ff" />
              <p className="text-xs text-[#6f988b]">Auto-approved rate: {formatPct(quality?.auto_approved_rate)} · Asset mapping coverage: {formatPct(quality?.asset_mapping_coverage)}</p>
              <p className="mt-2 text-xs text-[#6f988b]">Ingestion freshness: {quality?.news_ingestion_freshness_minutes != null ? `${quality.news_ingestion_freshness_minutes.toFixed(1)} min` : "-"}</p>
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
    <div className="rounded-[22px] border border-[#11352b] bg-[#07121a] px-4 py-3 shadow-[0_16px_36px_rgba(0,0,0,0.28)]">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#4d7669]">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-[#e6fff8]">{value}</p>
      <p className="mt-1 text-xs text-[#6f988b]">{hint}</p>
    </div>
  );
}
