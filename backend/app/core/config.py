from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "InboundCheck API"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    FRONTEND_URL: str = "http://localhost:3000"

    # Security & CORS Settings
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Supabase Configuration
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""

    # Shopify App Integration Configuration
    SHOPIFY_API_KEY: str = ""
    SHOPIFY_API_SECRET: str = ""

    # Stripe Billing Configuration
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_STARTER: str = "price_starter_monthly"
    STRIPE_PRICE_GROWTH: str = "price_growth_monthly"
    STRIPE_PRICE_ENTERPRISE: str = "price_enterprise_monthly"

    # V3 Roadmap - Open-Weights LLM Adapter Configuration
    LLM_API_BASE: str = "https://api.moonshot.cn/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL_NAME: str = "moonshot-v1-8k"

    # Telegram Real-Time Bot Alert Engine Configuration
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # V3 Roadmap - DNS Provider APIs
    CLOUDFLARE_API_TOKEN: str = ""
    GODADDY_API_KEY: str = ""
    GODADDY_API_SECRET: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
