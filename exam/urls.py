# exam/urls.py
"""
API 路由（APIView 版）
每个视图类通过 .as_view() 注册
"""
from django.urls import path
from . import views

urlpatterns = [
    # 公共接口
    path('exams/', views.ExamListView.as_view(), name='exam-list'),
    path('exams/<int:exam_id>/login/', views.CandidateLoginView.as_view(), name='candidate-login'),

    # 考生认证接口
    path('exams/<int:exam_id>/paper/', views.GetPaperView.as_view(), name='get-paper'),
    path('exams/<int:exam_id>/paper/status/', views.PaperStatusView.as_view(), name='paper-status'),
    path('exams/<int:exam_id>/submit/', views.SubmitPaperView.as_view(), name='submit-paper'),
    path('exams/<int:exam_id>/result/', views.ExamResultView.as_view(), name='exam-result'),
    path('exams/<int:exam_id>/paper-questions/<int:pq_id>/answer/',
         views.SubmitAnswerView.as_view(), name='submit-answer'),
]