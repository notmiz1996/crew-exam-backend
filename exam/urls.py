# exam/urls.py

"""
API 路由配置（§4.7）
"""
from django.urls import path
from . import views

urlpatterns = [
    path('exams/', views.exam_list, name='exam-list'),
    path('exams/<int:exam_id>/login/', views.candidate_login, name='exam-login'),
    path('exams/<int:exam_id>/paper/', views.get_paper, name='exam-paper'),
    path('exams/<int:exam_id>/paper-questions/<int:pq_id>/answer/', views.submit_answer, name='exam-answer'),
    path('exams/<int:exam_id>/paper/status/', views.paper_status, name='exam-status'),
    path('exams/<int:exam_id>/submit/', views.submit_paper, name='exam-submit'),
    path('exams/<int:exam_id>/result/', views.exam_result, name='exam-result'),
]