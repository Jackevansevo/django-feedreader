"""
Django settings for feedreader project.

Generated by 'django-admin startproject' using Django 4.0.5.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.0/ref/settings/
"""
import os
from pathlib import Path

import environ
from django.urls import reverse_lazy

env = environ.Env(
    # set casting, default value
    DEBUG=(bool, False),
    SECRET_KEY=(
        str,
        "django-insecure-+l=yrd#r#nfshb!(xn4i#&8^_-q*yr38pyt9(j6rr2o^q&4z3r",
    ),
)

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Take environment variables from .env file
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

# False if not in os.environ because of casting above
DEBUG = env("DEBUG")

# Raises Django's ImproperlyConfigured
# exception if SECRET_KEY not in os.environ
SECRET_KEY = env("SECRET_KEY")

LOGIN_REDIRECT_URL = reverse_lazy("feeds:index")
LOGOUT_REDIRECT_URL = reverse_lazy("account_login")

HOSTNAME = os.environ.get("HOSTNAME", "localhost")

# Load server IP from environment variable
if not DEBUG:
    ALLOWED_HOSTS = [HOSTNAME]
else:
    ALLOWED_HOSTS = ["*"]


# Application definition

SITE_ID = 1

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": [
            "profile",
            "email",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
        },
    }
}


INSTALLED_APPS = [
    "feeds.apps.FeedsConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.sites",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG:
    INSTALLED_APPS.append("debug_toolbar")
    INSTALLED_APPS.append("django_browser_reload")

    MIDDLEWARE.append("debug_toolbar.middleware.DebugToolbarMiddleware")
    MIDDLEWARE.append(
        "django_browser_reload.middleware.BrowserReloadMiddleware",
    )

    INTERNAL_IPS = ["127.0.0.1"]

    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

    from django.contrib.messages import constants as message_constants

    MESSAGE_LEVEL = message_constants.DEBUG

ROOT_URLCONF = "feedreader.urls"

FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "feeds.views.subscriptions_by_category",
            ],
        },
    },
]


AUTHENTICATION_BACKENDS = [
    # Needed to login by username in Django admin, regardless of `allauth`
    "django.contrib.auth.backends.ModelBackend",
    # `allauth` specific authentication methods, such as login by e-mail
    "allauth.account.auth_backends.AuthenticationBackend",
]


WSGI_APPLICATION = "feedreader.wsgi.application"


# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases


if DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "/data/db.sqlite3",
        }
    }

# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",  # noqa
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = "en-gb"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/


if not DEBUG:
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME")
    AWS_S3_ENDPOINT_URL = f"https://{AWS_S3_REGION_NAME}.digitaloceanspaces.com"
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}
    AWS_DEFAULT_ACL = "public-read"
    INSTALLED_APPS += ["storages"]
    MIDDLEWARE += [
        "django.middleware.cache.UpdateCacheMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.cache.FetchFromCacheMiddleware",
    ]

MEDIA_URL = "media/"

MEDIA_ROOT = BASE_DIR / "media"

STATIC_URL = "static/"

STATIC_ROOT = BASE_DIR / "static"

# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


CSRF_TRUSTED_ORIGINS = [f"https://{HOSTNAME}"]
