import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export const api = axios.create({
  baseURL: API_URL,
  headers: { "Content-Type": "application/json" },
});

// Attach JWT token from localStorage on every request
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401: attempt silent token refresh, then retry. Clear tokens on failure.
let _isRefreshing = false;
let _refreshQueue: Array<(token: string | null) => void> = [];

function _processQueue(token: string | null) {
  _refreshQueue.forEach((cb) => cb(token));
  _refreshQueue = [];
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    // Only handle 401, skip if already retried or it's the refresh call itself
    if (
      error.response?.status !== 401 ||
      original._retry ||
      original.url?.includes("/auth/refresh")
    ) {
      return Promise.reject(error);
    }
    original._retry = true;

    if (_isRefreshing) {
      // Queue subsequent 401s while refresh is in flight
      return new Promise((resolve, reject) => {
        _refreshQueue.push((newToken) => {
          if (newToken) {
            original.headers.Authorization = `Bearer ${newToken}`;
            resolve(api(original));
          } else {
            reject(error);
          }
        });
      });
    }

    _isRefreshing = true;
    const refreshToken = typeof window !== "undefined" ? localStorage.getItem("refresh_token") : null;

    if (!refreshToken) {
      // No refresh token — clear everything and signal logout
      if (typeof window !== "undefined") {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        window.dispatchEvent(new Event("auth:logout"));
      }
      _isRefreshing = false;
      _processQueue(null);
      return Promise.reject(error);
    }

    try {
      const { data } = await api.post("/auth/refresh", { refresh_token: refreshToken });
      const newAccess: string = data.access_token;
      const newRefresh: string = data.refresh_token;
      localStorage.setItem("access_token", newAccess);
      localStorage.setItem("refresh_token", newRefresh);
      api.defaults.headers.common.Authorization = `Bearer ${newAccess}`;
      original.headers.Authorization = `Bearer ${newAccess}`;
      _processQueue(newAccess);
      return api(original);
    } catch {
      // Refresh failed — wipe tokens, tell the UI to log out
      if (typeof window !== "undefined") {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        window.dispatchEvent(new Event("auth:logout"));
      }
      _processQueue(null);
      return Promise.reject(error);
    } finally {
      _isRefreshing = false;
    }
  }
);

// ─── Types ────────────────────────────────────────────────────────────────────

export interface EventListItem {
  id: string;
  title: string;
  event_type: string;
  country?: string;
  severity?: number;
  confidence_score?: number;
  published_at?: string;
  impact_count: number;
  tags?: string[];
  affected_assets?: {
    ticker: string;
    name?: string;
    impact_direction: string;
    impact_strength?: number;
    confidence_score?: number;
  }[];
}

export interface NewsArticle {
  id: string;
  title: string;
  source: string;
  url: string;
  published_at?: string;
  sentiment_score?: number;
  language_code?: string;
  language_confidence?: number;
  relevance_score?: number;
  relevance_label?: string;
  nlp_processed_at?: string;
  snippet?: string;
  category: string;
  matched_event_type?: string;
  created_at: string;
}

export interface UserProfile {
  id: string;
  email: string;
  username: string;
  role: string;
  subscription_plan: string;
  created_at: string;
}

export interface ReviewArticle {
  id: string;
  title: string;
  source: string;
  url: string;
  published_at?: string;
}

export interface EventReviewItem {
  id: string;
  title: string;
  description?: string;
  event_type: string;
  country?: string;
  region?: string;
  severity?: number;
  status: string;
  confidence_score?: number;
  published_at?: string;
  created_at: string;
  articles: ReviewArticle[];
  tags: string[];
  affected_assets: {
    ticker: string;
    name?: string;
    impact_direction: string;
    impact_strength?: number;
    confidence_score?: number;
  }[];
}

export interface ReviewDecisionInput {
  title?: string;
  description?: string;
  event_type?: string;
  country?: string;
  region?: string;
  severity?: number;
  confidence_score?: number;
}

export interface Board {
  id: string;
  user_id: string;
  title: string;
  description?: string;
  visibility: string;
  cover_image_url?: string;
  created_at: string;
  pin_count: number;
}

export interface BoardCreateInput {
  title: string;
  description?: string;
  visibility?: "public" | "private";
  cover_image_url?: string;
}

export interface Pin {
  id: string;
  board_id: string;
  content_type: "event" | "asset" | "prediction" | "news";
  content_id: string;
  note?: string;
  position: number;
  created_at: string;
}

export interface PinCreateInput {
  board_id: string;
  content_type: "event" | "asset" | "prediction" | "news";
  content_id: string;
  note?: string;
  position?: number;
}

export interface PinUpdateInput {
  note?: string;
  position?: number;
}

export interface PinReorderInput {
  pin_ids: string[];
}

export interface MarketQuote {
  ticker: string;
  price: number;
  currency: string;
  as_of: string;
  source: string;
  cache_hit: boolean;
}

export interface OHLCVPoint {
  timestamp: string;
  open?: number;
  high?: number;
  low?: number;
  close: number;
  volume?: number;
}

export interface MarketOHLCV {
  ticker: string;
  interval: string;
  points: OHLCVPoint[];
  source: string;
  cache_hit: boolean;
}

export interface MarketFundamentals {
  ticker: string;
  currency: string;
  market_cap?: number;
  pe_ratio?: number;
  eps?: number;
  dividend_yield?: number;
  week_52_high?: number;
  week_52_low?: number;
  as_of: string;
  source: string;
  cache_hit: boolean;
}

export interface MarketStreamPriceUpdate {
  type: "price_update";
  ticker: string;
  price: number;
  currency: string;
  as_of: string;
  source: string;
}

export interface EventHeatmapPoint {
  country: string;
  event_count: number;
  avg_severity: number;
  avg_confidence: number;
  conflict_share: number;
  latitude?: number;
  longitude?: number;
}

export interface QualitySummary {
  classification_accuracy?: number;
  nlp_latency_p95_seconds?: number;
  auto_approved_rate?: number;
  review_queue_backlog: number;
  news_ingestion_freshness_minutes?: number;
  asset_mapping_coverage?: number;
}

export interface PredictionItem {
  id: string;
  event_id: string;
  asset_id: string;
  event_title: string;
  event_type: string;
  ticker: string;
  asset_name?: string;
  predicted_direction: "up" | "down" | "neutral";
  predicted_change_pct?: number;
  prediction_horizon: string;
  confidence_score?: number;
  model_version: string;
  predicted_at: string;
  resolve_at?: string;
  actual_change_pct?: number;
  outcome: "correct" | "wrong" | "partial" | "pending";
  resolved_at?: string;
  model_accuracy?: number;
  event_type_accuracy?: number;
  eligible_for_display: boolean;
  feature_enabled: boolean;
}

export interface PredictionSummary {
  total_predictions: number;
  resolved_predictions: number;
  pending_predictions: number;
  overall_accuracy?: number;
  feature_enabled: boolean;
  display_accuracy_threshold: number;
  auto_disable_threshold: number;
  by_event_type?: Record<string, { total: number; correct: number; accuracy: number }>;
  by_model?: Record<string, { total: number; correct: number; accuracy: number }>;
  by_horizon?: Record<string, { total: number; correct: number; accuracy: number }>;
}

export interface AssetSummary {
  id: string;
  ticker: string;
  name: string;
  asset_type: string;
  sector?: string;
  industry?: string;
  country?: string;
  exchange?: string;
  currency: string;
}

export interface WatchlistLatestImpact {
  event_id: string;
  event_title: string;
  event_type: string;
  impact_direction: string;
  impact_strength?: number;
  confidence_score?: number;
  published_at?: string;
}

export interface WatchlistItem {
  id: string;
  user_id: string;
  asset_id: string;
  created_at: string;
  asset: AssetSummary;
  latest_impact?: WatchlistLatestImpact | null;
}

export interface WatchlistCreateInput {
  asset_id?: string;
  ticker?: string;
}

export interface AlertRule {
  id: string;
  user_id: string;
  asset_id?: string;
  ticker?: string;
  asset_name?: string;
  event_type?: string;
  threshold?: number;
  is_active: boolean;
  created_at: string;
}

export interface AlertCreateInput {
  asset_id?: string;
  ticker?: string;
  event_type?: string;
  threshold?: number;
  is_active?: boolean;
}

export interface AlertUpdateInput {
  asset_id?: string;
  ticker?: string;
  event_type?: string;
  threshold?: number;
  is_active?: boolean;
}

export interface BoardTemplate {
  slug: string;
  title: string;
  description: string;
  suggested_visibility: "public" | "private";
}

export interface AlertPreferences {
  email_enabled: boolean;
  web_push_enabled: boolean;
  web_push_tokens: string[];
  email_delivery_ready: boolean;
  web_push_delivery_ready: boolean;
}

export interface AlertPreferencesUpdateInput {
  email_enabled?: boolean;
  web_push_enabled?: boolean;
  web_push_tokens?: string[];
}

export interface BillingPlan {
  id: "free" | "pro" | "institutional";
  name: string;
  price_monthly?: number | null;
  currency: string;
  features: string[];
}

export interface BillingLimits {
  subscription_plan: "free" | "pro" | "institutional";
  boards_used: number;
  boards_limit?: number | null;
  alerts_used: number;
  alerts_limit?: number | null;
  predictions_remaining_today?: number | null;
  predictions_daily_limit?: number | null;
  stripe_configured: boolean;
  institutional_api_enabled: boolean;
}

export interface CheckoutSessionInput {
  plan: "pro" | "institutional";
}

export interface BillingSession {
  url: string;
}

export interface ApiKeyRecord {
  id: string;
  name: string;
  key_prefix: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
  created_at: string;
}

export interface ApiKeyCreateInput {
  name: string;
}

export interface ApiKeyCreateResult extends ApiKeyRecord {
  api_key: string;
}

export interface AccuracyMetrics {
  overall_accuracy?: number;
  total_resolved: number;
  total_correct: number;
  by_event_type: Record<string, { total: number; correct: number; accuracy: number }>;
  by_model: Record<string, { total: number; correct: number; accuracy: number }>;
  by_horizon: Record<string, { total: number; correct: number; accuracy: number }>;
}

export interface MarketSnapshotItem {
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

export interface MarketSnapshotPayload {
  snapshot: MarketSnapshotItem[];
  last_updated: string | null;
  source_status: { binance: string; polygon: string };
}

// ─── API functions ────────────────────────────────────────────────────────────

export const fetchEvents = async (params?: {
  event_type?: string;
  country?: string;
  q?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<EventListItem[]> => {
  const { data } = await api.get("/events", { params });
  return data;
};

export const fetchNews = async (params?: {
  q?: string;
  category?: string;
  limit?: number;
  offset?: number;
}): Promise<NewsArticle[]> => {
  const { data } = await api.get("/news", { params });
  return data;
};

export const fetchMyBoards = async (): Promise<Board[]> => {
  const { data } = await api.get("/boards");
  return data;
};

export const fetchPublicBoards = async (limit = 50): Promise<Board[]> => {
  const { data } = await api.get("/boards/public", { params: { limit } });
  return data;
};

export const createBoard = async (payload: BoardCreateInput): Promise<Board> => {
  const { data } = await api.post("/boards", payload);
  return data;
};

export const fetchBoardById = async (boardId: string): Promise<Board> => {
  const { data } = await api.get(`/boards/${boardId}`);
  return data;
};

export const fetchBoardPins = async (boardId: string): Promise<Pin[]> => {
  const { data } = await api.get(`/boards/${boardId}/pins`);
  return data;
};

export const fetchPins = async (params?: {
  board_id?: string;
  limit?: number;
  offset?: number;
}): Promise<Pin[]> => {
  const { data } = await api.get("/pins", { params });
  return data;
};

export const createPin = async (payload: PinCreateInput): Promise<Pin> => {
  const { data } = await api.post("/pins", payload);
  return data;
};

export const reorderBoardPins = async (
  boardId: string,
  payload: PinReorderInput
): Promise<Pin[]> => {
  const { data } = await api.patch(`/boards/${boardId}/pins/reorder`, payload);
  return data;
};

export const updatePin = async (pinId: string, payload: PinUpdateInput): Promise<Pin> => {
  const { data } = await api.patch(`/pins/${pinId}`, payload);
  return data;
};

export const deletePin = async (pinId: string): Promise<void> => {
  await api.delete(`/pins/${pinId}`);
};

export const fetchMe = async (): Promise<UserProfile> => {
  const { data } = await api.get("/users/me");
  return data;
};

export const fetchEventHeatmap = async (params?: {
  days?: number;
  limit?: number;
  event_type?: string;
}): Promise<EventHeatmapPoint[]> => {
  const { data } = await api.get("/events/heatmap", { params });
  return data;
};

export const fetchQualitySummary = async (): Promise<QualitySummary> => {
  const { data } = await api.get("/events/quality/summary");
  return data;
};

export const fetchPredictions = async (params?: {
  event_id?: string;
  ticker?: string;
  horizon?: string;
  history_only?: boolean;
  published_only?: boolean;
  limit?: number;
  offset?: number;
}): Promise<PredictionItem[]> => {
  const { data } = await api.get("/predictions", { params });
  return data;
};

export const fetchPredictionSummary = async (): Promise<PredictionSummary> => {
  const { data } = await api.get("/predictions/summary");
  return data;
};

export const fetchPredictionAccuracy = async (): Promise<AccuracyMetrics> => {
  const { data } = await api.get("/predictions/accuracy");
  return data;
};

export const fetchMarketSnapshot = async (): Promise<MarketSnapshotPayload> => {
  const { data } = await api.get("/market/snapshot");
  return data;
};

export const fetchPendingReviewEvents = async (limit = 50): Promise<EventReviewItem[]> => {
  const { data } = await api.get("/events/review/pending", { params: { limit } });
  return data;
};

export const editPendingReviewEvent = async (
  eventId: string,
  payload: ReviewDecisionInput
): Promise<EventReviewItem> => {
  const { data } = await api.patch(`/events/review/${eventId}`, payload);
  return data;
};

export const approveReviewEvent = async (
  eventId: string,
  payload?: ReviewDecisionInput
): Promise<{ id: string; status: string; message: string }> => {
  const { data } = await api.post(`/events/review/${eventId}/approve`, payload ?? {});
  return data;
};

export const rejectReviewEvent = async (
  eventId: string
): Promise<{ id: string; status: string; message: string }> => {
  const { data } = await api.post(`/events/review/${eventId}/reject`);
  return data;
};

export const fetchMarketQuote = async (
  ticker: string,
  options?: { refresh?: boolean }
): Promise<MarketQuote> => {
  const { data } = await api.get(`/market/quote/${encodeURIComponent(ticker)}`, {
    params: options?.refresh ? { refresh: true } : undefined,
  });
  return data;
};

export const fetchMarketOHLCV = async (
  ticker: string,
  params?: { interval?: string; limit?: number; refresh?: boolean }
): Promise<MarketOHLCV> => {
  const { data } = await api.get(`/market/ohlcv/${encodeURIComponent(ticker)}`, { params });
  return data;
};

export const fetchMarketHistorical1Y = async (
  ticker: string,
  options?: { refresh?: boolean }
): Promise<MarketOHLCV> => {
  const { data } = await api.get(`/market/historical/${encodeURIComponent(ticker)}`, {
    params: options?.refresh ? { refresh: true } : undefined,
  });
  return data;
};

export const fetchMarketFundamentals = async (
  ticker: string,
  options?: { refresh?: boolean }
): Promise<MarketFundamentals> => {
  const { data } = await api.get(`/market/fundamentals/${encodeURIComponent(ticker)}`, {
    params: options?.refresh ? { refresh: true } : undefined,
  });
  return data;
};

export const fetchWatchlist = async (): Promise<WatchlistItem[]> => {
  const { data } = await api.get("/watchlists");
  return data;
};

export const createWatchlist = async (payload: WatchlistCreateInput): Promise<WatchlistItem> => {
  const { data } = await api.post("/watchlists", payload);
  return data;
};

export const deleteWatchlist = async (watchlistId: string): Promise<void> => {
  await api.delete(`/watchlists/${watchlistId}`);
};

export const fetchAlerts = async (): Promise<AlertRule[]> => {
  const { data } = await api.get("/alerts");
  return data;
};

export const createAlert = async (payload: AlertCreateInput): Promise<AlertRule> => {
  const { data } = await api.post("/alerts", payload);
  return data;
};

export const updateAlert = async (
  alertId: string,
  payload: AlertUpdateInput
): Promise<AlertRule> => {
  const { data } = await api.patch(`/alerts/${alertId}`, payload);
  return data;
};

export const deleteAlert = async (alertId: string): Promise<void> => {
  await api.delete(`/alerts/${alertId}`);
};

export const fetchBoardTemplates = async (): Promise<BoardTemplate[]> => {
  const { data } = await api.get("/boards/templates");
  return data;
};

export const createBoardFromTemplate = async (
  slug: string,
  visibility: "public" | "private" = "private"
): Promise<Board> => {
  const { data } = await api.post(`/boards/templates/${slug}`, null, { params: { visibility } });
  return data;
};

export const fetchAlertPreferences = async (): Promise<AlertPreferences> => {
  const { data } = await api.get("/users/me/preferences");
  return data;
};

export const updateAlertPreferences = async (
  payload: AlertPreferencesUpdateInput
): Promise<AlertPreferences> => {
  const { data } = await api.patch("/users/me/preferences", payload);
  return data;
};

export const fetchBillingPlans = async (): Promise<BillingPlan[]> => {
  const { data } = await api.get("/billing/plans");
  return data;
};

export const fetchBillingLimits = async (): Promise<BillingLimits> => {
  const { data } = await api.get("/billing/limits");
  return data;
};

export const createCheckoutSession = async (
  payload: CheckoutSessionInput
): Promise<BillingSession> => {
  const { data } = await api.post("/billing/checkout-session", payload);
  return data;
};

export const createPortalSession = async (): Promise<BillingSession> => {
  const { data } = await api.post("/billing/portal-session");
  return data;
};

export const fetchApiKeys = async (): Promise<ApiKeyRecord[]> => {
  const { data } = await api.get("/billing/api-keys");
  return data;
};

export const createApiKey = async (
  payload: ApiKeyCreateInput
): Promise<ApiKeyCreateResult> => {
  const { data } = await api.post("/billing/api-keys", payload);
  return data;
};

export const revokeApiKey = async (keyId: string): Promise<void> => {
  await api.delete(`/billing/api-keys/${keyId}`);
};

export const getMarketWsUrl = (tickers: string[] = []): string => {
  const normalizedApi = API_URL.replace(/\/+$/, "");
  const wsBase = normalizedApi.replace(/^http:\/\//i, "ws://").replace(/^https:\/\//i, "wss://");
  const query = tickers.length ? `?tickers=${encodeURIComponent(tickers.join(","))}` : "";
  return `${wsBase}/market/ws${query}`;
};

export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
}

export const loginUser = async (email: string, password: string): Promise<AuthTokenResponse> => {
  const { data } = await api.post<AuthTokenResponse>("/auth/login", { email, password });
  if (typeof window !== "undefined") {
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("refresh_token", data.refresh_token);
  }
  return data;
};

export const registerUser = async (email: string, username: string, password: string): Promise<UserProfile> => {
  const { data } = await api.post<UserProfile>("/auth/register", { email, username, password });
  return data;
};
