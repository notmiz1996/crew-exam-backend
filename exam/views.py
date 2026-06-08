# exam/views.py

"""
考生端 7 个 REST API 视图（T-07 + T-08 + T-09）
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .models import Exam, ExamPaper, ExamPaperQuestion, Answer, Candidate, ExamCandidate
from .serializers import ExamListSerializer, success_response, error_response
from .authentication import ExamJWTAuthentication, generate_token
from .services.grading import grade_paper

logger = logging.getLogger('exam')


# 1. GET /api/exams/
@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def exam_list(request):
    exams = Exam.objects.all().order_by('-start_time')
    serializer = ExamListSerializer(exams, many=True)
    logger.info('考试列表访问 | count=%d', exams.count())
    return Response(success_response(serializer.data))


# 2. POST /api/exams/{exam_id}/login/
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def candidate_login(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)
    id_card = request.data.get('id_card', '').upper()

    try:
        candidate = Candidate.objects.get(id_card=id_card)
    except Candidate.DoesNotExist:
        return Response(error_response(1001, '该身份证号未在本场考试考生名单中'))

    try:
        exam_candidate = ExamCandidate.objects.get(exam=exam, candidate=candidate)
    except ExamCandidate.DoesNotExist:
        return Response(error_response(1001, '该身份证号未在本场考试考生名单中'))

    now = timezone.now()
    if now > exam.end_time:
        return Response(error_response(1002, '本场考试已结束'))
    if now < exam.start_time:
        return Response(error_response(1003, '本场考试尚未开始'))

    try:
        exam_paper = ExamPaper.objects.get(exam=exam, candidate=candidate)
        paper_status = exam_paper.status
    except ExamPaper.DoesNotExist:
        paper_status = 'pending'

    token = generate_token(candidate, exam)
    exp_time = exam.end_time + timedelta(minutes=30)

    return Response(success_response({
        'token': token,
        'candidate_name': candidate.name,
        'exam_id': exam.id,
        'paper_status': paper_status,
        'expires_at': exp_time.strftime('%Y-%m-%dT%H:%M:%S'),
    }))

# 3. GET /api/exams/{exam_id}/paper/
@api_view(['GET'])
@authentication_classes([ExamJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_paper(request, exam_id):
    exam_paper = request.auth

    # ── 试卷尚未生成 → 友好提示 ──
    if exam_paper is None:
        return Response(error_response(1006, '试卷尚未生成，请联系管理员生成试卷'))

    if exam_paper.status == 'finished':
        return Response(error_response(1004, '已交卷，不可操作'))

    if exam_paper.status == 'pending':
        affected = ExamPaper.objects.filter(
            id=exam_paper.id, status='pending'
        ).update(status='in_progress', started_at=timezone.now())
        if affected > 0:
            exam_paper.refresh_from_db()
        else:
            exam_paper.refresh_from_db()
            if exam_paper.status == 'finished':
                return Response(error_response(1004, '已交卷，不可操作'))

    questions = exam_paper.questions.select_related(
        'question__question_type'
    ).all().order_by('sort_order')

    question_data = []
    for epq in questions:
        try:
            selected = epq.answer.selected_answer
        except Answer.DoesNotExist:
            selected = None
        question_data.append({
            'id': epq.sort_order,
            'sort_order': epq.sort_order,
            'question_type': epq.question.question_type.code,
            'stem': epq.question.stem,
            'options': epq.shuffled_options,
            'score': epq.score,
            'selected_answer': selected,
        })

    remaining = exam_paper.exam.duration_minutes * 60
    if exam_paper.started_at:
        elapsed = (timezone.now() - exam_paper.started_at).total_seconds()
        remaining = max(0, int(exam_paper.exam.duration_minutes * 60 - elapsed))

    return Response(success_response({
        'paper_id': exam_paper.id,
        'status': exam_paper.status,
        'total_count': len(question_data),
        'duration_seconds': exam_paper.exam.duration_minutes * 60,
        'remaining_seconds': remaining,
        'questions': question_data,
    }))
# # 3. GET /api/exams/{exam_id}/paper/
# @api_view(['GET'])
# @authentication_classes([ExamJWTAuthentication])
# @permission_classes([IsAuthenticated])
# def get_paper(request, exam_id):
#     exam_paper = request.auth
#
#     if exam_paper.status == 'finished':
#         return Response(error_response(1004, '已交卷，不可操作'))
#
#     if exam_paper.status == 'pending':
#         affected = ExamPaper.objects.filter(
#             id=exam_paper.id, status='pending'
#         ).update(status='in_progress', started_at=timezone.now())
#         if affected > 0:
#             exam_paper.refresh_from_db()
#         else:
#             exam_paper.refresh_from_db()
#             if exam_paper.status == 'finished':
#                 return Response(error_response(1004, '已交卷，不可操作'))
#
#     questions = exam_paper.questions.select_related(
#         'question__question_type'
#     ).all().order_by('sort_order')
#
#     question_data = []
#     for epq in questions:
#         try:
#             selected = epq.answer.selected_answer
#         except Answer.DoesNotExist:
#             selected = None
#         question_data.append({
#             'id': epq.sort_order,
#             'sort_order': epq.sort_order,
#             'question_type': epq.question.question_type.code,
#             'stem': epq.question.stem,
#             'options': epq.shuffled_options,
#             'score': epq.score,
#             'selected_answer': selected,
#         })
#
#     remaining = exam_paper.exam.duration_minutes * 60
#     if exam_paper.started_at:
#         elapsed = (timezone.now() - exam_paper.started_at).total_seconds()
#         remaining = max(0, int(exam_paper.exam.duration_minutes * 60 - elapsed))
#
#     return Response(success_response({
#         'paper_id': exam_paper.id,
#         'status': exam_paper.status,
#         'total_count': len(question_data),
#         'duration_seconds': exam_paper.exam.duration_minutes * 60,
#         'remaining_seconds': remaining,
#         'questions': question_data,
#     }))


# 4. POST .../paper-questions/{pq_id}/answer/
@api_view(['POST'])
@authentication_classes([ExamJWTAuthentication])
@permission_classes([IsAuthenticated])
def submit_answer(request, exam_id, pq_id):
    exam_paper = request.auth
    logger.info('提交答案 | exam_paper_id=%s pq_id=%s data=%s',
                exam_paper.id if exam_paper else None, pq_id, request.data)
    if exam_paper.status == 'finished':
        return Response(error_response(1004, '已交卷，不可继续答题'))
    if exam_paper.status != 'in_progress':
        return Response(error_response(1009, '当前无进行中的考试'))

    if exam_paper.started_at:
        elapsed = (timezone.now() - exam_paper.started_at).total_seconds()
        if elapsed > exam_paper.exam.duration_minutes * 60:
            return Response(error_response(1007, '考试时间已到，无法提交答案'))

    try:
        epq = ExamPaperQuestion.objects.get(sort_order=pq_id, exam_paper=exam_paper)
    except ExamPaperQuestion.DoesNotExist:
        return Response(error_response(1006, '题目不存在'))

    # ── 获取前端答案 ──
    selected = request.data.get('selected_answer') or request.data.get('answer')

    # ── 判断题兼容：前端传文本（"正确"/"错误" → "A"/"B"） ──
    qt_code = epq.question.question_type.code
    if selected is not None and selected != '' and qt_code == 'judgment':
        shuffled_options = epq.shuffled_options
        # 建立选项文本 → 字母的映射
        text_to_letter = {}
        for i, opt in enumerate(shuffled_options):
            opt_text = opt.split('. ', 1)[-1] if '. ' in opt else opt
            text_to_letter[opt_text] = chr(ord('A') + i)
        # 同义词映射
        synonym_map = {
            '正确': ['对', '正确', '是', 'true', 'T', '√'],
            '错误': ['错', '错误', '否', 'false', 'F', '×'],
        }
        matched = False
        for opt_text, letter in text_to_letter.items():
            if selected.strip() == opt_text:
                selected = letter
                matched = True
                break
        if not matched:
            # 试试同义词
            for synonym_group in synonym_map.values():
                if selected.strip() in synonym_group:
                    for opt_text, letter in text_to_letter.items():
                        if opt_text in synonym_group:
                            selected = letter
                            matched = True
                            break
                if matched:
                    break

    # ── 答案格式校验 ──
    if selected is not None and selected != '':
        shuffled_options = epq.shuffled_options
        option_letters = [chr(ord('A') + i) for i in range(len(shuffled_options))]
        parts = [p.strip().upper() for p in selected.split(',')]
        for part in parts:
            if part not in option_letters:
                return Response(error_response(1011, '答案格式无效'))
        if len(parts) > 1:
            parts = list(dict.fromkeys(parts))
            selected = ','.join(parts)
        selected_value = selected
    else:
        selected_value = None

    answer, created = Answer.objects.update_or_create(
        exam_paper_question=epq,
        defaults={
            'selected_answer': selected_value,
            'answered_at': timezone.now(),
            'is_correct': None,
            'score': 0,
        },
    )

    return Response(success_response({
        'question_id': pq_id,
        'selected_answer': selected_value,
        'saved': True,
    }))

# 5. GET /api/exams/{exam_id}/paper/status/
@api_view(['GET'])
@authentication_classes([ExamJWTAuthentication])
@permission_classes([IsAuthenticated])
def paper_status(request, exam_id):
    exam_paper = request.auth

    if exam_paper.status == 'in_progress' and exam_paper.started_at:
        elapsed = (timezone.now() - exam_paper.started_at).total_seconds()
        if elapsed > exam_paper.exam.duration_minutes * 60:
            affected = ExamPaper.objects.filter(
                id=exam_paper.id, status='in_progress'
            ).update(status='finished', submitted_at=timezone.now())
            if affected > 0:
                exam_paper.refresh_from_db()
                grade_paper(exam_paper)

    remaining = 0
    if exam_paper.status == 'finished':
        remaining = 0
    elif exam_paper.started_at:
        elapsed = (timezone.now() - exam_paper.started_at).total_seconds()
        remaining = max(0, int(exam_paper.exam.duration_minutes * 60 - elapsed))
    else:
        remaining = exam_paper.exam.duration_minutes * 60

    answered_count = Answer.objects.filter(
        exam_paper_question__exam_paper=exam_paper, selected_answer__isnull=False
    ).count()

    return Response(success_response({
        'status': exam_paper.status,
        'remaining_seconds': remaining,
        'answered_count': answered_count,
        'total_count': exam_paper.questions.count(),
    }))


# 6. POST /api/exams/{exam_id}/submit/
@api_view(['POST'])
@authentication_classes([ExamJWTAuthentication])
@permission_classes([IsAuthenticated])
def submit_paper(request, exam_id):
    exam_paper = request.auth

    if exam_paper.status == 'finished':
        return Response(error_response(1004, '已交卷，不可操作'))
    if exam_paper.status != 'in_progress':
        return Response(error_response(1009, '当前无进行中的考试'))

    affected = ExamPaper.objects.filter(
        id=exam_paper.id, status='in_progress'
    ).update(status='finished', submitted_at=timezone.now())

    if affected == 0:
        exam_paper.refresh_from_db()
        if exam_paper.status == 'finished':
            return Response(error_response(1004, '已交卷，不可操作'))
        return Response(error_response(1009, '当前无进行中的考试'))

    exam_paper.refresh_from_db()
    total_score = grade_paper(exam_paper)

    return Response(success_response({'total_score': float(total_score)}))


# 7. GET /api/exams/{exam_id}/result/
@api_view(['GET'])
@authentication_classes([ExamJWTAuthentication])
@permission_classes([IsAuthenticated])
def exam_result(request, exam_id):
    exam_paper = request.auth

    if exam_paper.status != 'finished':
        return Response(error_response(1010, '考试尚未结束，无法查看成绩'))

    return Response(success_response({
        'total_score': float(exam_paper.total_score),
        'submitted_at': exam_paper.submitted_at.strftime('%Y-%m-%dT%H:%M:%S'),
    }))