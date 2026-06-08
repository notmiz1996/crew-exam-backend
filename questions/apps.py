# questions/apps.py

"""
题库应用配置
"""
from django.apps import AppConfig

class QuestionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'questions'
    verbose_name = '题库管理'