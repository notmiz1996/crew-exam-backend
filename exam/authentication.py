# exam/authentication.py

"""
JWT 认证类（§4.2 ExamJWTAuthentication）

Payload 结构：
  {
    "candidate_id": 1,
    "exam_id": 1,
    "exp": 1719123456  // exam.end_time + 30分钟
  }
"""
import jwt
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from rest_framework import authentication, exceptions
from .models import Candidate, ExamPaper


class ExamJWTAuthentication(authentication.BaseAuthentication):
    """
    考生端 JWT 认证类

    authenticate() 返回 (candidate, exam_paper)
      → request.user = candidate
      → request.auth = exam_paper
      → exam_paper 可能为 None（试卷尚未生成）
    """

    def authenticate(self, request):
        auth_header = request.headers.get('Authorization', '')

        if not auth_header.startswith('Bearer '):
            return None  # 匿名访问

        token = auth_header[7:]

        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=['HS256'],
            )
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed({
                'code': 1005, 'message': '登录已过期，请重新登录',
            })
        except jwt.InvalidTokenError:
            raise exceptions.AuthenticationFailed({
                'code': 1005, 'message': '无效凭证',
            })

        candidate_id = payload.get('candidate_id')
        exam_id = payload.get('exam_id')

        if not candidate_id or not exam_id:
            raise exceptions.AuthenticationFailed({
                'code': 1005, 'message': '无效凭证',
            })

        try:
            candidate = Candidate.objects.get(id=candidate_id)
        except Candidate.DoesNotExist:
            raise exceptions.AuthenticationFailed({
                'code': 1005, 'message': '无效凭证',
            })

        # ── 不强制 ExamPaper 存在，允许为 None ──
        # ExamPaper 在 Admin「生成试卷」后才存在
        # 如果不存在，request.auth = None，由视图层处理
        try:
            exam_paper = ExamPaper.objects.get(
                exam_id=exam_id, candidate_id=candidate_id,
            )
        except ExamPaper.DoesNotExist:
            exam_paper = None

        return (candidate, exam_paper)


def generate_token(candidate, exam) -> str:
    """
    为考生签发 JWT token
    有效期：exam.end_time + 30分钟（P2-001）
    """
    exp_time = exam.end_time + timedelta(minutes=30)
    if timezone.is_naive(exp_time):
        exp_time = timezone.make_aware(exp_time)

    payload = {
        'candidate_id': candidate.id,
        'exam_id': exam.id,
        'exp': exp_time,
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

# # exam/authentication.py
#
# """
# JWT 认证类（§4.2 ExamJWTAuthentication）
#
# Payload 结构：
#   {
#     "candidate_id": 1,
#     "exam_id": 1,
#     "exp": 1719123456  // exam.end_time + 30分钟
#   }
# """
# import jwt
# from datetime import timedelta
# from django.conf import settings
# from django.utils import timezone
# from rest_framework import authentication, exceptions
# from .models import Candidate, ExamPaper
#
#
# class ExamJWTAuthentication(authentication.BaseAuthentication):
#     """
#     考生端 JWT 认证类
#
#     authenticate() 返回 (candidate, exam_paper)
#       → request.user = candidate
#       → request.auth = exam_paper
#     """
#
#     def authenticate(self, request):
#         auth_header = request.headers.get('Authorization', '')
#
#         if not auth_header.startswith('Bearer '):
#             return None  # 匿名访问
#
#         token = auth_header[7:]
#
#         try:
#             payload = jwt.decode(
#                 token, settings.SECRET_KEY, algorithms=['HS256'],
#             )
#         except jwt.ExpiredSignatureError:
#             raise exceptions.AuthenticationFailed({
#                 'code': 1005, 'message': '登录已过期，请重新登录',
#             })
#         except jwt.InvalidTokenError:
#             raise exceptions.AuthenticationFailed({
#                 'code': 1005, 'message': '无效凭证',
#             })
#
#         candidate_id = payload.get('candidate_id')
#         exam_id = payload.get('exam_id')
#
#         if not candidate_id or not exam_id:
#             raise exceptions.AuthenticationFailed({
#                 'code': 1005, 'message': '无效凭证',
#             })
#
#         try:
#             candidate = Candidate.objects.get(id=candidate_id)
#             exam_paper = ExamPaper.objects.get(
#                 exam_id=exam_id, candidate_id=candidate_id,
#             )
#         except (Candidate.DoesNotExist, ExamPaper.DoesNotExist):
#             raise exceptions.AuthenticationFailed({
#                 'code': 1005, 'message': '无效凭证',
#             })
#
#         return (candidate, exam_paper)
#
#
# def generate_token(candidate, exam) -> str:
#     """
#     为考生签发 JWT token
#     有效期：exam.end_time + 30分钟（P2-001）
#     """
#     exp_time = exam.end_time + timedelta(minutes=30)
#     if timezone.is_naive(exp_time):
#         exp_time = timezone.make_aware(exp_time)
#
#     payload = {
#         'candidate_id': candidate.id,
#         'exam_id': exam.id,
#         'exp': exp_time,
#     }
#
#     return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')