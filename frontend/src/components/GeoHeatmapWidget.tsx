"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { AlertTriangle, Globe2, MapPin, Zap } from "lucide-react";

import { fetchEventHeatmap, type EventHeatmapPoint } from "@/lib/api";
import {
  Map as MapComponent,
  useMap,
  MapMarker,
  MarkerContent,
  MarkerTooltip,
  MapControls,
} from "@/components/ui/map";

/* ─── Types ───────────────────────────────────────────────────────────────── */
interface HotspotPoint extends EventHeatmapPoint {
  latitude: number;
  longitude: number;
}

/* ─── Severity logic ──────────────────────────────────────────────────────── */
function severityColor(conflictShare: number, eventCount: number) {
  const heat = Math.min(
    1,
    conflictShare * 0.55 + Math.min(eventCount / 15, 1) * 0.45,
  );
  if (heat >= 0.65) return "#f04e5e";
  if (heat >= 0.35) return "#e6a832";
  return "#20a07f";
}

function severitySize(eventCount: number) {
  return Math.max(8, Math.min(28, eventCount * 2));
}

/* ─── Heatmap Layer (uses MapLibre heatmap layer type) ────────────────────── */
function HeatmapLayer({ hotspots }: { hotspots: HotspotPoint[] }) {
  const { map, isLoaded } = useMap();
  const id = useId();
  const sourceId = `heatmap-source-${id}`;
  const heatLayerId = `heatmap-layer-${id}`;

  const geoJson = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: hotspots.map((h) => ({
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [h.longitude, h.latitude],
        },
        properties: {
          event_count: h.event_count,
          conflict_share: h.conflict_share,
          severity: h.avg_severity,
        },
      })),
    }),
    [hotspots],
  );

  useEffect(() => {
    if (!map || !isLoaded) return;

    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: "geojson", data: geoJson });
    }

    if (!map.getLayer(heatLayerId)) {
      map.addLayer({
        id: heatLayerId,
        type: "heatmap",
        source: sourceId,
        maxzoom: 8,
        paint: {
          "heatmap-weight": [
            "interpolate", ["linear"], ["get", "event_count"],
            1, 0.2, 15, 1,
          ],
          "heatmap-intensity": [
            "interpolate", ["linear"], ["zoom"],
            0, 0.4, 4, 1.2,
          ],
          "heatmap-color": [
            "interpolate", ["linear"], ["heatmap-density"],
            0, "rgba(32, 160, 127, 0)",
            0.2, "rgba(32, 160, 127, 0.4)",
            0.4, "rgba(230, 168, 50, 0.6)",
            0.6, "rgba(230, 168, 50, 0.8)",
            0.8, "rgba(240, 78, 94, 0.85)",
            1, "rgba(240, 78, 94, 1)",
          ],
          "heatmap-radius": [
            "interpolate", ["linear"], ["zoom"],
            0, 12, 4, 28, 8, 40,
          ],
          "heatmap-opacity": [
            "interpolate", ["linear"], ["zoom"],
            0, 0.65, 6, 0.4,
          ],
        },
      });
    }

    return () => {
      try {
        if (map.getLayer(heatLayerId)) map.removeLayer(heatLayerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
      } catch { /* ignore */ }
    };
  }, [map, isLoaded, sourceId, heatLayerId, geoJson]);

  // Update data when hotspots change
  useEffect(() => {
    if (!map || !isLoaded) return;
    const source = map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined;
    source?.setData(geoJson);
  }, [map, isLoaded, sourceId, geoJson]);

  return null;
}

/* ─── Hotspot Marker ──────────────────────────────────────────────────────── */
function HotspotMarker({ hotspot }: { hotspot: HotspotPoint }) {
  const color = severityColor(hotspot.conflict_share, hotspot.event_count);
  const size = severitySize(hotspot.event_count);

  return (
    <MapMarker longitude={hotspot.longitude} latitude={hotspot.latitude}>
      <MarkerContent>
        <div className="relative flex items-center justify-center" style={{ width: size * 2.5, height: size * 2.5 }}>
          {/* Outer pulse ring */}
          <div
            className="absolute inset-0 animate-ping rounded-full opacity-20"
            style={{ backgroundColor: color, animationDuration: "3s" }}
          />
          {/* Mid glow */}
          <div
            className="absolute rounded-full opacity-25"
            style={{
              backgroundColor: color,
              width: size * 1.4,
              height: size * 1.4,
            }}
          />
          {/* Core dot */}
          <div
            className="relative rounded-full border border-white/40 shadow-lg"
            style={{
              backgroundColor: color,
              width: Math.max(8, size * 0.5),
              height: Math.max(8, size * 0.5),
              boxShadow: `0 0 12px ${color}80`,
            }}
          />
        </div>
      </MarkerContent>
      <MarkerTooltip offset={20}>
        <div className="min-w-[140px]">
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            <p className="font-semibold text-[#e6fff8]">{hotspot.country}</p>
          </div>
          <div className="mt-1 space-y-0.5 text-[10px] text-[#8db8ab]">
            <p>{hotspot.event_count} events</p>
            <p>Severity: {hotspot.avg_severity.toFixed(1)}</p>
            <p>Conflict: {(hotspot.conflict_share * 100).toFixed(0)}%</p>
          </div>
        </div>
      </MarkerTooltip>
    </MapMarker>
  );
}

/* ─── Widget ──────────────────────────────────────────────────────────────── */
export function GeoHeatmapWidget() {
  const { data: heatmap, isLoading } = useQuery({
    queryKey: ["dashboard-heatmap"],
    queryFn: () => fetchEventHeatmap({ days: 14, limit: 60 }),
    staleTime: 60_000,
  });

  const hotspots = useMemo(() => {
    if (!heatmap) return [];
    return heatmap
      .filter(
        (p): p is HotspotPoint =>
          p.latitude !== undefined && p.longitude !== undefined,
      )
      .sort(
        (a, b) =>
          b.event_count * b.conflict_share -
          a.event_count * a.conflict_share,
      );
  }, [heatmap]);

  const top5 = hotspots.slice(0, 5);
  const totalEvents = hotspots.reduce((sum, h) => sum + h.event_count, 0);
  const totalConflict = hotspots.filter((h) => h.conflict_share > 0.4).length;

  return (
    <section className="mt-6">
      <div className="mb-3 flex items-center gap-2">
        <Globe2 className="h-5 w-5 text-geo-600" />
        <h2 className="text-base font-bold text-gray-900">
          Geopolitical Heatmap
        </h2>
        <span className="rounded-full bg-geo-50 px-2 py-0.5 text-xs font-medium text-geo-700">
          14d window
        </span>
      </div>

      <div className="overflow-hidden rounded-[24px] border border-gray-200 bg-[#061014] shadow-lg">
        {/* Map area — powered by mapcn / MapLibre GL */}
        <div className="relative h-[340px]">
          {isLoading ? (
            <div className="flex h-full items-center justify-center bg-[#061014]">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#20a07f] border-t-transparent" />
            </div>
          ) : (
            <MapComponent
              theme="dark"
              center={[20, 18]}
              zoom={1.2}
              scrollZoom={false}
              renderWorldCopies={false}
              minZoom={0.8}
              maxZoom={6}
              dragRotate={false}
            >
              <MapControls
                position="bottom-right"
                showZoom
                showFullscreen={false}
              />

              {/* Native MapLibre heatmap layer for ambient glow */}
              <HeatmapLayer hotspots={hotspots} />

              {/* Individual hotspot markers with tooltips */}
              {hotspots.map((h) => (
                <HotspotMarker key={h.country} hotspot={h} />
              ))}
            </MapComponent>
          )}

          {/* Summary overlay */}
          <div className="absolute bottom-3 left-3 z-20 flex items-center gap-3">
            <div className="rounded-xl bg-[#06101a]/90 px-3 py-2 backdrop-blur-sm">
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#86ffdc]">
                {hotspots.length} regions
              </p>
              <p className="text-xs text-[#6f988b]">
                {totalEvents} events tracked
              </p>
            </div>
            {totalConflict > 0 && (
              <div className="flex items-center gap-1 rounded-xl bg-rose-900/60 px-3 py-2 backdrop-blur-sm">
                <AlertTriangle className="h-3.5 w-3.5 text-rose-300" />
                <span className="text-xs font-bold text-rose-200">
                  {totalConflict} high-conflict
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Top hotspots strip */}
        <div className="border-t border-[#0f2e25] px-4 py-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Zap className="h-3.5 w-3.5 text-[#ffd782]" />
              <span className="text-[10px] font-bold uppercase tracking-[0.22em] text-[#ffd782]">
                Top Hotspots
              </span>
            </div>
            <Link
              href="/map"
              className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#86ffdc] transition-colors hover:text-[#b8ffe8]"
            >
              View full map →
            </Link>
          </div>

          {top5.length > 0 ? (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5">
              {top5.map((h) => (
                <div
                  key={h.country}
                  className="rounded-xl border border-[#17372f] bg-[#08161d] px-3 py-2 transition-colors hover:bg-[#0c1d26]"
                >
                  <div className="flex items-center gap-1.5">
                    <MapPin
                      className="h-3 w-3"
                      style={{
                        color: severityColor(
                          h.conflict_share,
                          h.event_count,
                        ),
                      }}
                    />
                    <p className="truncate text-xs font-semibold text-[#e6fff8]">
                      {h.country}
                    </p>
                  </div>
                  <p className="mt-1 text-[10px] text-[#6f988b]">
                    {h.event_count} events · sev{" "}
                    {h.avg_severity.toFixed(1)}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-[#6f988b]">
              No hotspot data available.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}