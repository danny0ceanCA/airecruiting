import os
from datetime import timedelta

import httpx
from openai import OpenAI

ADMIN_ROLES = {"admin", "junior_admin"}

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "").rstrip("/")

JWT_SECRET = "secret"
ALGORITHM = "HS256"

REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 7)))
REFRESH_TOKEN_LOOKUP_PREFIX = "refresh_token_lookup"
REFRESH_TOKEN_USER_PREFIX = "refresh_token_user"
ACCESS_TOKEN_TTL = timedelta(hours=1)

ACTIVITY_LOG_KEY = "activity_logs"
EMAIL_OPEN_TOKENS_KEY = "email_open_tokens"
STUDENT_LOAD_TIME_KEY = "metrics:student_load_time"

DEFAULT_LICENSES: dict[str, str] = {
    "lvn": "Licensed Vocational Nurse",
    "ma": "Medical Assistant",
}

NURSING_FEEDS = {
    "American Nurse": "https://www.myamericannurse.com/feed/",
}

NURSING_NEWS_CACHE_KEY = "cache:nursing_news"
NURSING_NEWS_TTL = 3600
RSS_HEADERS = {"User-Agent": "Mozilla/5.0"}

REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise RuntimeError("Missing REDIS_URL in .env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), http_client=httpx.Client())
