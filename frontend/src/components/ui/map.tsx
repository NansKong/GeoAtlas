"use client";

import MapLibreGL, { type PopupOptions, type MarkerOptions } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useId,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { X, Minus, Plus, Locate, Maximize, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

/* ─── Default tile styles ─────────────────────────────────────────────────── */
const defaultStyles = {
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
};

type Theme = "light" | "dark";

function getDocumentTheme(): Theme | null {
  if (typeof document === "undefined") return null;
  if (document.documentElement.classList.contains("dark")) return "dark";
  if (document.documentElement.classList.contains("light")) return "light";
  return null;
}

function getSystemTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function useResolvedTheme(themeProp?: Theme): Theme {
  const [detectedTheme, setDetectedTheme] = useState<Theme>(
    () => getDocumentTheme() ?? getSystemTheme(),
  );

  useEffect(() => {
    if (themeProp) return;
    const observer = new MutationObserver(() => {
      const docTheme = getDocumentTheme();
      if (docTheme) setDetectedTheme(docTheme);
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleSystemChange = (e: MediaQueryListEvent) => {
      if (!getDocumentTheme()) setDetectedTheme(e.matches ? "dark" : "light");
    };
    mediaQuery.addEventListener("change", handleSystemChange);
    return () => {
      observer.disconnect();
      mediaQuery.removeEventListener("change", handleSystemChange);
    };
  }, [themeProp]);

  return themeProp ?? detectedTheme;
}

/* ─── Map context ─────────────────────────────────────────────────────────── */
type MapContextValue = { map: MapLibreGL.Map | null; isLoaded: boolean };
const MapContext = createContext<MapContextValue | null>(null);

function useMap() {
  const context = useContext(MapContext);
  if (!context) throw new Error("useMap must be used within a Map component");
  return context;
}

type MapViewport = {
  center: [number, number];
  zoom: number;
  bearing: number;
  pitch: number;
};

type MapStyleOption = string | MapLibreGL.StyleSpecification;
type MapRef = MapLibreGL.Map;

type MapProps = {
  children?: ReactNode;
  className?: string;
  theme?: Theme;
  styles?: { light?: MapStyleOption; dark?: MapStyleOption };
  projection?: MapLibreGL.ProjectionSpecification;
  viewport?: Partial<MapViewport>;
  onViewportChange?: (viewport: MapViewport) => void;
  loading?: boolean;
} & Omit<MapLibreGL.MapOptions, "container" | "style">;

function DefaultLoader() {
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#031018]/50 backdrop-blur-sm">
      <div className="flex gap-1">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#86ffdc]/60" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#86ffdc]/60 [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#86ffdc]/60 [animation-delay:300ms]" />
      </div>
    </div>
  );
}

function getViewport(map: MapLibreGL.Map): MapViewport {
  const center = map.getCenter();
  return {
    center: [center.lng, center.lat],
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  };
}

/* ─── Map component ───────────────────────────────────────────────────────── */
const Map = forwardRef<MapRef, MapProps>(function Map(
  {
    children,
    className,
    theme: themeProp,
    styles,
    projection,
    viewport,
    onViewportChange,
    loading = false,
    ...props
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [mapInstance, setMapInstance] = useState<MapLibreGL.Map | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const [isStyleLoaded, setIsStyleLoaded] = useState(false);
  const currentStyleRef = useRef<MapStyleOption | null>(null);
  const styleTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const internalUpdateRef = useRef(false);
  const resolvedTheme = useResolvedTheme(themeProp);

  const isControlled = viewport !== undefined && onViewportChange !== undefined;
  const onViewportChangeRef = useRef(onViewportChange);
  onViewportChangeRef.current = onViewportChange;

  const mapStyles = useMemo(
    () => ({
      dark: styles?.dark ?? defaultStyles.dark,
      light: styles?.light ?? defaultStyles.light,
    }),
    [styles],
  );

  useImperativeHandle(ref, () => mapInstance as MapLibreGL.Map, [mapInstance]);

  const clearStyleTimeout = useCallback(() => {
    if (styleTimeoutRef.current) {
      clearTimeout(styleTimeoutRef.current);
      styleTimeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;

    const initialStyle =
      resolvedTheme === "dark" ? mapStyles.dark : mapStyles.light;
    currentStyleRef.current = initialStyle;

    const map = new MapLibreGL.Map({
      container: containerRef.current,
      style: initialStyle,
      renderWorldCopies: false,
      attributionControl: { compact: true },
      ...props,
      ...viewport,
    });

    const styleDataHandler = () => {
      clearStyleTimeout();
      styleTimeoutRef.current = setTimeout(() => {
        setIsStyleLoaded(true);
        if (projection) map.setProjection(projection);
      }, 100);
    };
    const loadHandler = () => setIsLoaded(true);
    const handleMove = () => {
      if (internalUpdateRef.current) return;
      onViewportChangeRef.current?.(getViewport(map));
    };

    map.on("load", loadHandler);
    map.on("styledata", styleDataHandler);
    map.on("move", handleMove);
    setMapInstance(map);

    return () => {
      clearStyleTimeout();
      map.off("load", loadHandler);
      map.off("styledata", styleDataHandler);
      map.off("move", handleMove);
      map.remove();
      setIsLoaded(false);
      setIsStyleLoaded(false);
      setMapInstance(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!mapInstance || !isControlled || !viewport) return;
    if (mapInstance.isMoving()) return;
    const current = getViewport(mapInstance);
    const next = {
      center: viewport.center ?? current.center,
      zoom: viewport.zoom ?? current.zoom,
      bearing: viewport.bearing ?? current.bearing,
      pitch: viewport.pitch ?? current.pitch,
    };
    if (
      next.center[0] === current.center[0] &&
      next.center[1] === current.center[1] &&
      next.zoom === current.zoom &&
      next.bearing === current.bearing &&
      next.pitch === current.pitch
    ) return;
    internalUpdateRef.current = true;
    mapInstance.jumpTo(next);
    internalUpdateRef.current = false;
  }, [mapInstance, isControlled, viewport]);

  useEffect(() => {
    if (!mapInstance || !resolvedTheme) return;
    const newStyle =
      resolvedTheme === "dark" ? mapStyles.dark : mapStyles.light;
    if (currentStyleRef.current === newStyle) return;
    clearStyleTimeout();
    currentStyleRef.current = newStyle;
    setIsStyleLoaded(false);
    mapInstance.setStyle(newStyle, { diff: true });
  }, [mapInstance, resolvedTheme, mapStyles, clearStyleTimeout]);

  const contextValue = useMemo(
    () => ({ map: mapInstance, isLoaded: isLoaded && isStyleLoaded }),
    [mapInstance, isLoaded, isStyleLoaded],
  );

  return (
    <MapContext.Provider value={contextValue}>
      <div
        ref={containerRef}
        className={cn("relative h-full w-full", className)}
      >
        {(!isLoaded || loading) && <DefaultLoader />}
        {mapInstance && children}
      </div>
    </MapContext.Provider>
  );
});

/* ─── Marker ──────────────────────────────────────────────────────────────── */
type MarkerContextValue = {
  marker: MapLibreGL.Marker;
  map: MapLibreGL.Map | null;
};
const MarkerContext = createContext<MarkerContextValue | null>(null);

function useMarkerContext() {
  const context = useContext(MarkerContext);
  if (!context) throw new Error("Marker components must be used within MapMarker");
  return context;
}

type MapMarkerProps = {
  longitude: number;
  latitude: number;
  children: ReactNode;
  onClick?: (e: MouseEvent) => void;
  onMouseEnter?: (e: MouseEvent) => void;
  onMouseLeave?: (e: MouseEvent) => void;
} & Omit<MarkerOptions, "element">;

function MapMarker({
  longitude,
  latitude,
  children,
  onClick,
  onMouseEnter,
  onMouseLeave,
  draggable = false,
  ...markerOptions
}: MapMarkerProps) {
  const { map } = useMap();
  const callbacksRef = useRef({ onClick, onMouseEnter, onMouseLeave });
  callbacksRef.current = { onClick, onMouseEnter, onMouseLeave };

  const marker = useMemo(() => {
    const m = new MapLibreGL.Marker({
      ...markerOptions,
      element: document.createElement("div"),
      draggable,
    }).setLngLat([longitude, latitude]);

    m.getElement()?.addEventListener("click", (e) => callbacksRef.current.onClick?.(e));
    m.getElement()?.addEventListener("mouseenter", (e) => callbacksRef.current.onMouseEnter?.(e));
    m.getElement()?.addEventListener("mouseleave", (e) => callbacksRef.current.onMouseLeave?.(e));
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map) return;
    marker.addTo(map);
    return () => { marker.remove(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  if (marker.getLngLat().lng !== longitude || marker.getLngLat().lat !== latitude) {
    marker.setLngLat([longitude, latitude]);
  }

  return (
    <MarkerContext.Provider value={{ marker, map }}>
      {children}
    </MarkerContext.Provider>
  );
}

/* ─── MarkerContent ───────────────────────────────────────────────────────── */
function MarkerContent({ children, className }: { children?: ReactNode; className?: string }) {
  const { marker } = useMarkerContext();
  return createPortal(
    <div className={cn("relative cursor-pointer", className)}>
      {children || <div className="relative h-4 w-4 rounded-full border-2 border-white bg-blue-500 shadow-lg" />}
    </div>,
    marker.getElement(),
  );
}

/* ─── MarkerPopup ─────────────────────────────────────────────────────────── */
type MarkerPopupProps = {
  children: ReactNode;
  className?: string;
  closeButton?: boolean;
} & Omit<PopupOptions, "className" | "closeButton">;

function MarkerPopup({
  children,
  className,
  closeButton = false,
  ...popupOptions
}: MarkerPopupProps) {
  const { marker, map } = useMarkerContext();
  const container = useMemo(() => document.createElement("div"), []);

  const popup = useMemo(() => {
    return new MapLibreGL.Popup({ offset: 16, ...popupOptions, closeButton: false })
      .setMaxWidth("none")
      .setDOMContent(container);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map) return;
    popup.setDOMContent(container);
    marker.setPopup(popup);
    return () => { marker.setPopup(null); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  const handleClose = () => popup.remove();

  return createPortal(
    <div className={cn(
      "relative max-w-[280px] rounded-xl border border-[#17372f] bg-[#08161d] p-3 text-[#e6fff8] shadow-lg",
      "animate-in fade-in-0 zoom-in-95 duration-200 ease-out",
      className,
    )}>
      {closeButton && (
        <button type="button" onClick={handleClose} aria-label="Close popup"
          className="absolute top-1 right-1 z-10 inline-flex h-5 w-5 cursor-pointer items-center justify-center rounded-sm text-[#6f988b] transition-colors hover:bg-[#0c1d26] hover:text-[#e6fff8]">
          <X className="h-3.5 w-3.5" />
        </button>
      )}
      {children}
    </div>,
    container,
  );
}

/* ─── MarkerTooltip ───────────────────────────────────────────────────────── */
type MarkerTooltipProps = {
  children: ReactNode;
  className?: string;
} & Omit<PopupOptions, "className" | "closeButton" | "closeOnClick">;

function MarkerTooltip({ children, className, ...popupOptions }: MarkerTooltipProps) {
  const { marker, map } = useMarkerContext();
  const container = useMemo(() => document.createElement("div"), []);

  const tooltip = useMemo(() => {
    return new MapLibreGL.Popup({ offset: 16, ...popupOptions, closeOnClick: true, closeButton: false })
      .setMaxWidth("none");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map) return;
    tooltip.setDOMContent(container);
    const handleMouseEnter = () => tooltip.setLngLat(marker.getLngLat()).addTo(map);
    const handleMouseLeave = () => tooltip.remove();
    marker.getElement()?.addEventListener("mouseenter", handleMouseEnter);
    marker.getElement()?.addEventListener("mouseleave", handleMouseLeave);
    return () => {
      marker.getElement()?.removeEventListener("mouseenter", handleMouseEnter);
      marker.getElement()?.removeEventListener("mouseleave", handleMouseLeave);
      tooltip.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  return createPortal(
    <div className={cn(
      "pointer-events-none rounded-lg border border-[#17372f] bg-[#08161d] px-2.5 py-1.5 text-xs text-[#e6fff8] shadow-lg",
      "animate-in fade-in-0 zoom-in-95 duration-200 ease-out",
      className,
    )}>
      {children}
    </div>,
    container,
  );
}

/* ─── MapControls ─────────────────────────────────────────────────────────── */
type MapControlsProps = {
  position?: "top-left" | "top-right" | "bottom-left" | "bottom-right";
  showZoom?: boolean;
  showLocate?: boolean;
  showFullscreen?: boolean;
  className?: string;
};

const positionClasses = {
  "top-left": "top-3 left-3",
  "top-right": "top-3 right-3",
  "bottom-left": "bottom-3 left-3",
  "bottom-right": "bottom-12 right-3",
};

function ControlButton({ onClick, label, children, disabled = false }: {
  onClick: () => void; label: string; children: ReactNode; disabled?: boolean;
}) {
  return (
    <button onClick={onClick} aria-label={label} type="button" disabled={disabled}
      className={cn(
        "flex h-8 w-8 items-center justify-center transition-all",
        "first:rounded-t-md last:rounded-b-md",
        "hover:bg-[#17372f] text-[#86ffdc]",
        "disabled:pointer-events-none disabled:opacity-50",
      )}>
      {children}
    </button>
  );
}

function MapControls({
  position = "bottom-right",
  showZoom = true,
  showLocate = false,
  showFullscreen = false,
  className,
}: MapControlsProps) {
  const { map } = useMap();
  const [waitingForLocation, setWaitingForLocation] = useState(false);

  const handleZoomIn = useCallback(() => { map?.zoomTo(map.getZoom() + 1, { duration: 300 }); }, [map]);
  const handleZoomOut = useCallback(() => { map?.zoomTo(map.getZoom() - 1, { duration: 300 }); }, [map]);

  const handleLocate = useCallback(() => {
    setWaitingForLocation(true);
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          map?.flyTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: 14, duration: 1500 });
          setWaitingForLocation(false);
        },
        () => setWaitingForLocation(false),
      );
    }
  }, [map]);

  const handleFullscreen = useCallback(() => {
    const container = map?.getContainer();
    if (!container) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else container.requestFullscreen();
  }, [map]);

  return (
    <div className={cn("absolute z-10 flex flex-col gap-1.5", positionClasses[position], className)}>
      {showZoom && (
        <div className="flex flex-col overflow-hidden rounded-md border border-[#17372f] bg-[#08161d] shadow-sm [&>button:not(:last-child)]:border-b [&>button:not(:last-child)]:border-[#17372f]">
          <ControlButton onClick={handleZoomIn} label="Zoom in"><Plus className="h-4 w-4" /></ControlButton>
          <ControlButton onClick={handleZoomOut} label="Zoom out"><Minus className="h-4 w-4" /></ControlButton>
        </div>
      )}
      {showLocate && (
        <div className="overflow-hidden rounded-md border border-[#17372f] bg-[#08161d] shadow-sm">
          <ControlButton onClick={handleLocate} label="Find my location" disabled={waitingForLocation}>
            {waitingForLocation ? <Loader2 className="h-4 w-4 animate-spin" /> : <Locate className="h-4 w-4" />}
          </ControlButton>
        </div>
      )}
      {showFullscreen && (
        <div className="overflow-hidden rounded-md border border-[#17372f] bg-[#08161d] shadow-sm">
          <ControlButton onClick={handleFullscreen} label="Toggle fullscreen"><Maximize className="h-4 w-4" /></ControlButton>
        </div>
      )}
    </div>
  );
}

/* ─── MapPopup (standalone, not tied to marker) ───────────────────────────── */
type MapPopupProps = {
  longitude: number;
  latitude: number;
  onClose?: () => void;
  children: ReactNode;
  className?: string;
  closeButton?: boolean;
} & Omit<PopupOptions, "className" | "closeButton">;

function MapPopup({
  longitude,
  latitude,
  onClose,
  children,
  className,
  closeButton = false,
  ...popupOptions
}: MapPopupProps) {
  const { map } = useMap();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const container = useMemo(() => document.createElement("div"), []);

  const popup = useMemo(() => {
    return new MapLibreGL.Popup({ offset: 16, ...popupOptions, closeButton: false })
      .setMaxWidth("none")
      .setLngLat([longitude, latitude]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map) return;
    const onCloseProp = () => onCloseRef.current?.();
    popup.on("close", onCloseProp);
    popup.setDOMContent(container);
    popup.addTo(map);
    return () => {
      popup.off("close", onCloseProp);
      if (popup.isOpen()) popup.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  if (popup.isOpen()) {
    if (popup.getLngLat().lng !== longitude || popup.getLngLat().lat !== latitude) {
      popup.setLngLat([longitude, latitude]);
    }
  }

  const handleClose = () => popup.remove();

  return createPortal(
    <div className={cn(
      "relative max-w-[280px] rounded-xl border border-[#17372f] bg-[#08161d] p-3 text-[#e6fff8] shadow-lg",
      "animate-in fade-in-0 zoom-in-95 duration-200 ease-out",
      className,
    )}>
      {closeButton && (
        <button type="button" onClick={handleClose} aria-label="Close popup"
          className="absolute top-1 right-1 z-10 inline-flex h-5 w-5 cursor-pointer items-center justify-center rounded-sm text-[#6f988b] transition-colors hover:bg-[#0c1d26] hover:text-[#e6fff8]">
          <X className="h-3.5 w-3.5" />
        </button>
      )}
      {children}
    </div>,
    container,
  );
}

/* ─── MapRoute ────────────────────────────────────────────────────────────── */
type MapRouteProps = {
  id?: string;
  coordinates: [number, number][];
  color?: string;
  width?: number;
  opacity?: number;
  dashArray?: [number, number];
};

function MapRoute({
  id: propId,
  coordinates,
  color = "#79ffd7",
  width = 3,
  opacity = 0.8,
  dashArray,
}: MapRouteProps) {
  const { map, isLoaded } = useMap();
  const autoId = useId();
  const id = propId ?? autoId;
  const sourceId = `route-source-${id}`;
  const layerId = `route-layer-${id}`;

  useEffect(() => {
    if (!isLoaded || !map) return;
    map.addSource(sourceId, {
      type: "geojson",
      data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [] } },
    });
    map.addLayer({
      id: layerId, type: "line", source: sourceId,
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": color, "line-width": width, "line-opacity": opacity,
        ...(dashArray && { "line-dasharray": dashArray }),
      },
    });
    return () => {
      try {
        if (map.getLayer(layerId)) map.removeLayer(layerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
      } catch { /* ignore */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, map]);

  useEffect(() => {
    if (!isLoaded || !map || coordinates.length < 2) return;
    const source = map.getSource(sourceId) as MapLibreGL.GeoJSONSource;
    if (source) {
      source.setData({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates } });
    }
  }, [isLoaded, map, coordinates, sourceId]);

  return null;
}

export {
  Map,
  useMap,
  MapMarker,
  MarkerContent,
  MarkerPopup,
  MarkerTooltip,
  MapPopup,
  MapControls,
  MapRoute,
};

export type { MapRef, MapViewport };
