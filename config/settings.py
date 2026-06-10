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
    'drf_spectacular',  # ← 新增
    'drf_spectacular_sidecar',  # ← 新增（离线 Swagger UI 资源）
    # 本地应用
    'questions',
    'exam',
    # 跨域
    'corsheaders',
    # 定时
    'django_q',
]

MIDDLEWARE = [
    # 跨域
    'corsheaders.middleware.CorsMiddleware',
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
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}


# ====== drf-spectacular 配置 ======
SPECTACULAR_SETTINGS = {
    'TITLE': '肇庆市船员履职技能大赛机考系统 API',
    'DESCRIPTION': """
船员履职技能大赛机考系统后端接口文档。

## 认证方式
- **Admin 端**：Django Session（通过 Admin 登录）
- **考生端**：JWT（通过 `/api/exams/{id}/login/` 获取 token）
  - 请求头：`Authorization: Bearer <token>`

## 接口一览
| 接口 | 说明 |
|------|------|
| `GET  /api/exams/` | 考试列表（公开） |
| `POST /api/exams/{id}/login/` | 考生登录（公开） |
| `GET  /api/exams/{id}/paper/` | 获取试卷（JWT） |
| `POST .../answer/` | 提交答案（JWT） |
| `GET  .../status/` | 考试状态（JWT） |
| `POST .../submit/` | 交卷（JWT） |
| `GET  .../result/` | 考试结果（JWT） |
    """.strip(),
    'VERSION': '1.0.0',
    # 使用 sidecar 离线 Swagger UI（避免 CDN 加载慢）
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
    # 中文
    'SWAGGER_UI_SETTINGS': {
        'lang': 'zh-cn',
    },
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


# CORS 配置（开发环境开放所有来源，生产环境请收紧）
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    'authorization',
    'content-type',
    'accept',
    'origin',
    'x-requested-with',
]

# 定时任务设置
Q_CLUSTER = {
    'name': 'crew_exam',
    'workers': 1,                # SQLite 仅建议单 worker
    'timeout': 120,              # 任务超时秒数
    'retry': 60,                 # 重试间隔
    'compress': True,            # 压缩传输
    'save_limit': 250,           # 保存最近 250 条执行记录
    'queue_limit': 10,           # 队列上限
    'orm': 'default',            # 使用 ORM 作为 broker（兼容 SQLite）
    'poll': 10,                  # 轮询间隔（秒），10 秒检查一次队列
    'label': 'Django Q',
}