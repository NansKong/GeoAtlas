from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_NAME: str = "GeoAtlas"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres.ehljoqkvqumrcmsmvhlk:geo%40tlas2026@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres?ssl=require"
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://postgres.ehljoqkvqumrcmsmvhlk:geo%40tlas2026@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres?sslmode=require"

    # Redis
    REDIS_URL: str = "rediss://default:gQAAAAAAApd4AAIgcDIwZjk5ZmVlYTk0OTA0YzJhOGM5MzZjMTUxZDhiMWQyYQ@engaging-shrew-169848.upstash.io:6379"
    CELERY_BROKER_URL: str = "rediss://default:gQAAAAAAApd4AAIgcDIwZjk5ZmVlYTk0OTA0YzJhOGM5MzZjMTUxZDhiMWQyYQ@engaging-shrew-169848.upstash.io:6379"
    CELERY_RESULT_BACKEND: str = "rediss://default:gQAAAAAAApd4AAIgcDIwZjk5ZmVlYTk0OTA0YzJhOGM5MzZjMTUxZDhiMWQyYQ@engaging-shrew-169848.upstash.io:6379"

    # JWT
    SECRET_KEY: str = "b7f2c4e1a8d93f5c6e2b4a9d1f7c3e8a5b6d9c2f4a7e1b3c6d8f0a2c5e7b9d1"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001,https://geo-atlas-two.vercel.app"

    @property
    def cors_origins(self) -> List[str]:
        origins = [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
        origins.append("https://geo-atlas-two.vercel.app")
        return list(set(origins))

    # News APIs
    NEWS_API_KEY: str = "f6e2d131b8354f25a1d0a871d8cefbc9"
    GDELT_BASE_URL: str = "http://api.gdeltproject.org/api/v2/doc/doc"
    EVENTREGISTRY_API_KEY: str = ""
    EVENTREGISTRY_BASE_URL: str = "https://eventregistry.org/api/v1/article/getArticles"
    MEDIASTACK_API_KEY: str = ""
    MEDIASTACK_BASE_URL: str = "http://api.mediastack.com/v1/news"
    WIKIDATA_SPARQL_URL: str = "https://query.wikidata.org/sparql"
    SEC_EDGAR_BASE_URL: str = "https://data.sec.gov"
    SEC_ARCHIVES_BASE_URL: str = "https://www.sec.gov/Archives"
    SEC_EDGAR_USER_AGENT: str = "GeoAtlas/0.1 (engineering@geoatlas.local)"
    NLP_ALLOWED_LANGUAGES: str = "en"
    NLP_MIN_LANGUAGE_CONFIDENCE: float = 0.80
    NLP_RELEVANCE_THRESHOLD: float = 0.58
    NLP_RELEVANCE_MODEL_MODE: str = "heuristic"
    NLP_RELEVANCE_MODEL_PATH: str = ""
    NLP_EVENT_MODEL_MODE: str = "heuristic"
    NLP_EVENT_MODEL_PATH: str = ""
    NLP_SENTIMENT_MODEL_MODE: str = "heuristic"
    NLP_SENTIMENT_MODEL_PATH: str = ""
    NLP_NER_MODEL_MODE: str = "heuristic"
    NLP_NER_MODEL_PATH: str = ""
    XGB_MODEL_PATH: str = "backend/tmp/phase4/models/xgboost_regime.joblib"
    NLP_MODEL_DEVICE: int = -1
    NLP_ENABLE_L2_KG_MAPPING: bool = True
    NLP_L2_HOP1_WEIGHT: float = 0.60
    NLP_L2_HOP2_WEIGHT: float = 0.35
    NLP_ENABLE_L3_SECTOR_MAPPING: bool = True
    NLP_L3_MAX_ASSETS_PER_SECTOR: int = 6
    NLP_L3_BASE_WEIGHT: float = 0.45
    NLP_ENABLE_L4_SIMILARITY_MAPPING: bool = True
    NLP_L4_LOOKBACK_EVENTS: int = 300
    NLP_L4_MIN_SIMILARITY: float = 0.38
    NLP_L4_MAX_ASSET_CANDIDATES: int = 5
    QUALITY_ENFORCE_GATES: bool = True
    QUALITY_MIN_CONFIDENCE: float = 0.55
    QUALITY_TEMPORAL_MAX_HOURS: int = 48

    # Market APIs
    POLYGON_API_KEY: str = "GPEr4eRE7IIBlUZY0G8u_oNjs8gSD7Rm"
    FINNHUB_API_KEY: str = "d6parp9r01qk3chjju7gd6parp9r01qk3chjju80"
    TWELVEDATA_API_KEY: str = "08bbbee230fa4f11acd28efdb6002551"
    EODHD_API_KEY: str = "69d7e9af258924.22691077"
    FCS_API_KEY: str = "qSwNxUmd7CqVF3IvUo95"
    ALPHA_VANTAGE_API_KEY: str = "99XOVBOLXXLRVQ4C"
    BINANCE_API_KEY: str = ""
    BINANCE_API_SECRET: str = ""
    MARKET_REQUIRE_LIVE_API: bool = False

    # Alpaca Market Data API (free Basic plan = IEX real-time + historical)
    ALPACA_API_KEY_ID: str = "PKKDZOVANCCMMPOZBZZT3EKPME"
    ALPACA_API_SECRET_KEY: str = "2TSoUyXQoxQmK38XMsEmaB9gSPwgf58zFsUj6Hu9peWE"

    # Elasticsearch
    ELASTICSEARCH_URL: str = "http://localhost:9200"

    # Email / push
    SENDGRID_API_KEY: str = ""
    FROM_EMAIL: str = "noreply@geoatlas.io"
    FCM_SERVER_KEY: str = ""

    # Billing / API access
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_PRO_MONTHLY: str = ""
    STRIPE_PRICE_INSTITUTIONAL_MONTHLY: str = ""
    STRIPE_SUCCESS_URL: str = "http://localhost:3000/pricing?status=success"
    STRIPE_CANCEL_URL: str = "http://localhost:3000/pricing?status=cancelled"
    STRIPE_PORTAL_RETURN_URL: str = "http://localhost:3000/pricing"
    INSTITUTIONAL_API_RATE_LIMIT_PER_MINUTE: int = 120


settings = Settings()
