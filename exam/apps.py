# exam/apps.py

"""
考试核心应用配置
"""
from django.apps import AppConfig

class ExamConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'exam'
    verbose_name = '考试管理'