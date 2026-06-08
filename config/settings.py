# config/settings.py

"""
Django 项目配置
- 使用 SQLite + WAL 模式（通过 signal 开启，保证事务安全）
- DRF 配置：SessionAuthentication（Admin）+ 自定义 JWT（考生端）
- 日志配置：标准 logging，覆盖全部关键操作（P1-003）
"""
import os
from pathlib import Path
from django.db.backends.signals import connection_created

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-+c1w&_0k7#x$z@v!q9%m^3n*b5s2r4t6y8u0i*o(p)a-df-g=h'

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # 第三方
    'rest_framework',
    # 本地应用
    'questions',
    'exam',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'config.wsgi.application'

# ====== 数据库：SQLite ======
# WAL 模式通过 connection_created signal 开启，见文件底部
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ====== 密码验证 ======
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
]

# ====== 国际化 ======
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# ====== 静态文件 ======
STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ====== DRF 配置（§4.2 认证机制） ======
REST_FRAMEWORK = {
    # Admin 端用 Session，考生端用自定义 JWT
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'exam.authentication.ExamJWTAuthentication',
    ],
    # 默认允许匿名访问（公开接口如登录、考试列表）
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    # 统一异常处理 — 不暴露内部堆栈
    'EXCEPTION_HANDLER': 'exam.utils.exception_handler.custom_exception_handler',
}

# ====== 日志配置（§12 日志框架，P1-003） ======
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[%(asctime)s] %(levelname)s [%(name)s] %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        'exam': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}

# ====== SQLite WAL 模式（§8.4 容灾方案） ======
# 使用 connection_created 信号开启 WAL 模式，替代不可用的 init_command
def activate_wal(sender, connection, **kwargs):
    """数据库连接创建时，开启 WAL 模式提升可靠性"""
    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")

connection_created.connect(activate_wal)