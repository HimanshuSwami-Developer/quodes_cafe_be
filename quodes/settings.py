"""Django settings for the Quodes Gaming backend."""
import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # exposes GROQ_API_KEY etc. to os.environ
# A key listed in .env (even empty) wins over the shell, so another project's
# EMAIL_* variables never leak into this one.
_DOTENV = dotenv_values(BASE_DIR / ".env")


def env(name, default=None):
    if name in _DOTENV:
        return _DOTENV[name] or (default if default is not None else "")
    return os.getenv(name, default)


def env_bool(name, default=False):
    return str(env(name, str(default)) or default).lower() in ("1", "true", "yes", "on")


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-only-for-local-development-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]

INSTALLED_APPS = [
    "unfold",  # admin theme, must come before django.contrib.admin
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "accounts",
    "catalog",
    "bookings",
    "support",
    "staff",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "quodes.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "quodes.wsgi.application"

# `manage.py test` always runs on local SQLite + disk, never on the real Neon / Cloudinary.
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"

# Postgres when DATABASE_URL is set (postgres://user:pass@host:5432/dbname), else local SQLite.
DATABASE_URL = "" if TESTING else env("DATABASE_URL", "")
if DATABASE_URL:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=int(env("DATABASE_CONN_MAX_AGE", "60")),
        conn_health_checks=True,
        # Hosted Postgres (Neon, Supabase, Render, RDS...) needs SSL; local Docker usually doesn't.
        ssl_require=env_bool("DATABASE_SSL", False),
    )}
    # Pooled hosts (Neon "-pooler", Supabase :6543, PgBouncer) run in transaction mode,
    # which breaks server-side cursors.
    if "pooler" in DATABASE_URL or ":6543" in DATABASE_URL or env_bool("DATABASE_POOLED", False):
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---- Uploaded files (game covers, payment screenshots, ticket attachments) ----
# With CLOUDINARY_URL set, uploads go to Cloudinary; otherwise they're saved under MEDIA_ROOT.
# Either CLOUDINARY_URL=cloudinary://<key>:<secret>@<cloud> or the three separate variables.
CLOUDINARY_URL = env("CLOUDINARY_URL", "")
if not CLOUDINARY_URL and env("CLOUDINARY_CLOUD_NAME") and env("CLOUDINARY_API_KEY") and env("CLOUDINARY_API_SECRET"):
    CLOUDINARY_URL = (f"cloudinary://{env('CLOUDINARY_API_KEY')}:{env('CLOUDINARY_API_SECRET')}"
                      f"@{env('CLOUDINARY_CLOUD_NAME')}")
CLOUDINARY_FOLDER = env("CLOUDINARY_FOLDER", "quodes")
USE_CLOUDINARY = bool(CLOUDINARY_URL) and not TESTING
if USE_CLOUDINARY:
    from quodes.storage import configure as _configure_cloudinary

    _configure_cloudinary(CLOUDINARY_URL)
    STORAGES = {
        # Public: game covers, served from the CDN, capped at 1200px wide.
        "default": {"BACKEND": "quodes.storage.CloudinaryStorage",
                    "OPTIONS": {"delivery": "upload", "max_width": 1200}},
        # Private: payment screenshots + ticket attachments, signed URLs only.
        "private": {"BACKEND": "quodes.storage.CloudinaryStorage",
                    "OPTIONS": {"delivery": "authenticated"}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"auth": "20/min", "otp": "5/min"},
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
}

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [o for o in env("CORS_ALLOWED_ORIGINS", "").split(",") if o]

# ---- Email (OTP codes + booking/ticket notifications) ----
# With EMAIL_HOST set, mail goes out over SMTP; otherwise it is printed to the console.
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
# EMAIL_USER / EMAIL_PASS / EMAIL_SECURE / REQUIRE_TLS (Nodemailer-style names) also work.
EMAIL_HOST_USER = env("EMAIL_HOST_USER") or env("EMAIL_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD") or env("EMAIL_PASS", "")
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", env_bool("EMAIL_SECURE", EMAIL_PORT == 465))
EMAIL_USE_TLS = not EMAIL_USE_SSL and env_bool("EMAIL_USE_TLS", env_bool("REQUIRE_TLS", EMAIL_PORT == 587))
EMAIL_TIMEOUT = 20
EMAIL_BACKEND = env("EMAIL_BACKEND") or (
    "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL") or (
    f"Quodes Gaming <{EMAIL_HOST_USER}>" if EMAIL_HOST_USER else "Quodes Gaming <no-reply@quodes.gg>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_REPLY_TO = env("EMAIL_REPLY_TO", "")
# Public base URL of this server, used for admin links in staff emails.
SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")
EMAIL_ASYNC = env_bool("EMAIL_ASYNC", True)
# Comma-separated desk addresses for "payment to verify" / "new ticket" alerts.
# Empty = every active staff user.
STAFF_ALERT_EMAILS = [e.strip() for e in env("STAFF_ALERT_EMAILS", "").split(",") if e.strip()]
# Players must confirm their email with a code before they can log in.
REQUIRE_EMAIL_VERIFICATION = env_bool("REQUIRE_EMAIL_VERIFICATION", True)

# Upload limits (bytes)
MAX_PROOF_BYTES = 5 * 1024 * 1024
MAX_COVER_BYTES = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024

# Groq vision model that reads payment screenshots (needs GROQ_API_KEY). Without a key
# the AI step is skipped and every proof goes straight to human verification.
GROQ_API_KEY = env("GROQ_API_KEY", "")
GROQ_MODEL = env("GROQ_MODEL", "qwen/qwen3.8-27b")
AI_VERIFY_ENABLED = env_bool("AI_VERIFY_ENABLED", True)
# Run the AI scan in a background thread (True) or inline in the request (False, used in tests).
AI_VERIFY_ASYNC = env_bool("AI_VERIFY_ASYNC", True)

# ---- Admin panel (django-unfold) -------------------------------------------------
from django.urls import reverse  # noqa: E402


def _blue():
    # Brand blue #2F6BFF scale
    return {"50": "#EEF3FF", "100": "#DCE6FF", "200": "#B9CDFF", "300": "#8FAFFF", "400": "#5E8BFF",
            "500": "#2F6BFF", "600": "#2457E0", "700": "#1A3FA8", "800": "#16338A", "900": "#122A6E", "950": "#0A1330"}


UNFOLD = {
    "SITE_TITLE": "Quodes Desk",
    "SITE_HEADER": "Quodes Gaming",
    "SITE_SUBHEADER": "Desk & admin",
    "SITE_SYMBOL": "sports_esports",
    "SITE_URL": "/admin/",
    "SHOW_VIEW_ON_SITE": False,
    "DASHBOARD_CALLBACK": "quodes.dashboard.dashboard_callback",
    "COLORS": {"primary": _blue()},
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {"title": "Desk", "items": [
                {"title": "Dashboard", "icon": "dashboard", "link": lambda request: reverse("admin:index")},
                {"title": "Verify payments", "icon": "verified", "badge": "quodes.dashboard.verify_badge",
                 "link": lambda request: reverse("admin:bookings_booking_changelist") + "?queue=verify"},
                {"title": "All bookings", "icon": "event_seat", "link": lambda request: reverse("admin:bookings_booking_changelist")},
                {"title": "Support tickets", "icon": "support_agent", "badge": "quodes.dashboard.ticket_badge",
                 "link": lambda request: reverse("admin:support_ticket_changelist")},
            ]},
            {"title": "Café", "items": [
                {"title": "Games", "icon": "stadia_controller", "link": lambda request: reverse("admin:catalog_game_changelist")},
                {"title": "Station types & rates", "icon": "devices", "link": lambda request: reverse("admin:catalog_stationtype_changelist")},
                {"title": "Stations", "icon": "chair", "link": lambda request: reverse("admin:catalog_station_changelist")},
                {"title": "Café settings", "icon": "storefront",
                 "link": lambda request: reverse("admin:catalog_cafesettings_change", args=[1])},
            ]},
            {"title": "Content", "items": [
                {"title": "FAQs", "icon": "help", "link": lambda request: reverse("admin:support_faq_changelist")},
                {"title": "Policies", "icon": "gavel", "link": lambda request: reverse("admin:support_policy_changelist")},
            ]},
            {"title": "People", "items": [
                {"title": "Players & staff", "icon": "group", "link": lambda request: reverse("admin:accounts_user_changelist")},
                {"title": "Staff roles", "icon": "admin_panel_settings", "link": lambda request: reverse("admin:auth_group_changelist"),
                 "permission": lambda request: request.user.is_superuser},
            ]},
        ],
    },
}
