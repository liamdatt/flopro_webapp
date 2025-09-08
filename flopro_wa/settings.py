# whatsapp_webapp/settings.py

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# ---- Security & env-driven config ----
# IMPORTANT: never keep a real secret here. Read from env with a safe default for dev.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-only-not-secure')

DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() == 'true'

# ---- n8n Configuration ----
N8N_API_BASE_URL = os.environ.get('N8N_API_BASE_URL', '')
N8N_API_KEY = os.environ.get('N8N_API_KEY', '')

# Accept hosts from env. In prod, set DJANGO_ALLOWED_HOSTS="app.example.com"
ALLOWED_HOSTS = (
    os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')
    if os.environ.get('DJANGO_ALLOWED_HOSTS')
    else ['localhost', '127.0.0.1']
)

# Needed for POST forms/cookies when served behind Cloudflare
# e.g. DJANGO_CSRF_ORIGIN="https://app.example.com"
CSRF_TRUSTED_ORIGINS = (
    [os.environ['DJANGO_CSRF_ORIGIN']]
    if os.environ.get('DJANGO_CSRF_ORIGIN')
    else []
)

# Trust the Cloudflare/ingress proxy for HTTPS
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# (Keep SECURE_SSL_REDIRECT off unless you confirm cloudflared sets X-Forwarded-Proto=https.)

# ---- Apps & middleware ----
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise must be early to serve static files in the container
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'flopro_wa.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'flopro_wa.wsgi.application'

# ---- Database (SQLite for now, path can come from env for persistence) ----
SQLITE_PATH = os.environ.get('SQLITE_PATH')  # e.g. "/data/db.sqlite3" set in .env
# --- Database: Postgres via env; fallback to SQLite for dev ---
DB_NAME = os.environ.get("POSTGRES_DB")
DB_USER = os.environ.get("POSTGRES_USER")
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD")
DB_HOST = os.environ.get("POSTGRES_HOST") or os.environ.get("DB_HOST")  # allow either
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

if all([DB_NAME, DB_USER, DB_PASSWORD, DB_HOST]):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": DB_NAME,
            "USER": DB_USER,
            "PASSWORD": DB_PASSWORD,
            "HOST": DB_HOST,
            "PORT": DB_PORT,
            "CONN_MAX_AGE": 60,  # keep-alive for perf
            "OPTIONS": {"sslmode": os.environ.get("POSTGRES_SSLMODE", "disable")},
        }
    }
else:
    # Fallback (works in dev or before DB is configured)
    SQLITE_PATH = os.environ.get("SQLITE_PATH")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": SQLITE_PATH if SQLITE_PATH else BASE_DIR / "db.sqlite3",
        }
    }


# ---- i18n ----
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ---- Static / Media ----
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
# If you need uploads, we’ll mount a volume and point this at /app/media
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---- Authentication URLs ----
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'
