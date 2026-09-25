import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    APP_URL = os.getenv("APP_URL", "http://localhost:5000")

    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    DATABASE_URL = os.getenv("DATABASE_URL", "")

    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
    PAYSTACK_BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")

    CRON_SECRET = os.getenv("CRON_SECRET", "")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")
    SMTP_TLS = os.getenv("SMTP_TLS", "true").lower() != "false"
    SMTP_SECURITY = os.getenv("SMTP_SECURITY", "")
    RESERVATION_HOLD_MINUTES = int(os.getenv("RESERVATION_HOLD_MINUTES", "15"))
    SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))

    PERMANENT_SESSION_LIFETIME = timedelta(days=SESSION_TTL_DAYS)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("FLASK_ENV") == "production"
    WTF_CSRF_TIME_LIMIT = None
    JSON_SORT_KEYS = False

    @classmethod
    def validate_production(cls):
        missing = []
        for name in ("FLASK_SECRET_KEY", "SUPABASE_URL", "DATABASE_URL", "CRON_SECRET"):
            if not os.getenv(name):
                missing.append(name)
        if not (os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")):
            missing.append("SUPABASE_PUBLISHABLE_KEY")
        return missing
