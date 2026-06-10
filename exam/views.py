# exam/views.py
"""
考生端 REST API 视图（APIView 版）
每个接口一个独立类，认证策略在类级别声明
包含显式考试状态检查（P0 修复）
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .models import Exam, ExamPaper, ExamPaperQuestion, Answer, Candidate, ExamCandidate
from .serializers import ExamListSerializer, success_response, error_response, CandidateVerifySerializer
from .authentication import ExamJWTAuthentication, generate_token
from .services.grading import grade_paper, force_finish_exam_papers

logger = logging.getLogger('exam')


# ============================================================
# 公共接口（无需认证）
# ============================================================
class CandidateVerifyView(APIView):
    """
    POST /api/candidates/verify/

    考生身份证验证 → 返回考生信息 + 待参加考试列表

    流程：
      1. 校验身份证号格式（18位）
      2. 查找 Candidate 记录
      3. 查找该考生报名的考试（通过 ExamCandidate）
      4. 仅返回未结束（PUBLISHED 且 end_time > now）的考试
      5. 标记每场考试的考生参与状态
    """
    authentication_classes = []  # 无需登录即可查询
    permission_classes = [AllowAny]  # 公开接口

    def post(self, request):
        serializer = CandidateVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        id_card = serializer.validated_data['id_card']

        # ── 1. 查找考生 ──
        try:
            candidate = Candidate.objects.get(id_card=id_card)
        except Candidate.DoesNotExist:
            return Response(
                {'error': '未找到该考生信息，请确认身份证号是否正确'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── 2. 查找该考生的考试报名记录 ──
        #    通过 ExamCandidate 查考试，带上 exam_paper 信息
        now = timezone.now()
        ec_qs = (
            ExamCandidate.objects
            .filter(candidate=candidate)
            .select_related('exam', 'exam_paper')
            .order_by('exam__start_time')
        )

        exams_data = []
        for ec in ec_qs:
            exam = ec.exam

            # 只展示"未结束"的考试：PUBLISHED 状态 + 结束时间未过
            if exam.status != Exam.Status.PUBLISHED:
                continue
            if exam.end_time <= now:
                continue

            # 判断该考生对这场考试的参与状态
            paper = ec.exam_paper
            if paper is None:
                candidate_status = 'not_started'  # 未开始
            elif paper.status == ExamPaper.Status.IN_PROGRESS:
                candidate_status = 'in_progress'  # 考试中
            elif paper.status == ExamPaper.Status.FINISHED:
                candidate_status = 'finished'  # 已交卷
            else:
                candidate_status = 'not_started'

            exams_data.append({
                'id': exam.id,
                'name': exam.name,
                'start_time': exam.start_time.strftime('%Y-%m-%d %H:%M'),
                'end_time': exam.end_time.strftime('%Y-%m-%d %H:%M'),
                'duration_minutes': exam.duration_minutes,
                'total_questions': exam.total_questions,
                'total_score': exam.total_score,
                'passing_score': exam.passing_score,
                'candidate_status': candidate_status,
            })

        # ── 3. 组装返回 ──
        return Response({
            'candidate': {
                'id': candidate.id,
                'name': candidate.name,
                'id_card': candidate.id_card,
            },
            'exams': exams_data,
        })

class ExamListView(APIView):
    """GET /api/exams/ — 考试列表"""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        exams = Exam.objects.filter(status=Exam.Status.PUBLISHED).order_by('-start_time')
        serializer = ExamListSerializer(exams, many=True)
        logger.info('考试列表访问 | count=%d', exams.count())
        return Response(success_response(serializer.data))


class CandidateLoginView(APIView):
    """
    POST /api/exams/{exam_id}/login/ — 考生登录
    - 校验身份证号是否在考生名单中
    - 显式考试状态检查（P0）
    - 校验时间窗口（未开始 / 已结束）
    - 考场关闭时自动强制交卷并批改
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, exam_id, format=None):
        exam = get_object_or_404(Exam, id=exam_id)

        # ============================================
        # 显式考试状态检查
        # ============================================
        if exam.status == Exam.Status.DRAFT:
            return Response(error_response(1012, '考试尚未发布'))
        if exam.status == Exam.Status.PAUSED:
            return Response(error_response(1013, '考试已暂停，请联系管理员'))
        if exam.status == Exam.Status.CANCELLED:
            return Response(error_response(1014, '本场考试已取消'))
        if exam.status == Exam.Status.FINISHED:
            return Response(error_response(1002, '本场考试已结束'))

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

        # 考场已关闭：先强制交卷批改，再返回错误
        if now > exam.end_time:
            count = force_finish_exam_papers(exam, candidate)
            if count > 0:
                logger.info('考场关闭时自动批改 | candidate=%s papers=%d', candidate.name, count)
            return Response(error_response(1002, '本场考试已结束'))

        # 考试未开始
        if now < exam.start_time:
            return Response(error_response(1003, '本场考试尚未开始'))

        # 正常登录
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


# ============================================================
# 考生认证接口（需要 JWT）
# ============================================================

class GetPaperView(APIView):
    """
    GET /api/exams/{exam_id}/paper/ — 获取试卷题目
    - 显式考试状态检查（P0）
    - 时间窗口检查（未开始 / 已关闭）
    - pending → in_progress 状态流转
    - 返回剩余时间
    """
    authentication_classes = [ExamJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, exam_id, format=None):
        exam = get_object_or_404(Exam, id=exam_id)
        exam_paper = request.auth
        now = timezone.now()

        # ============================================
        # 显式考试状态检查
        # ============================================
        if exam.status == Exam.Status.DRAFT:
            return Response(error_response(1012, '考试尚未发布'))
        if exam.status == Exam.Status.PAUSED:
            return Response(error_response(1013, '考试已暂停，请联系管理员'))
        if exam.status == Exam.Status.CANCELLED:
            return Response(error_response(1014, '本场考试已取消'))
        if exam.status == Exam.Status.FINISHED:
            return Response(error_response(1002, '本场考试已结束'))

        # 考场已关闭：强制交卷
        if now > exam.end_time:
            if exam_paper and exam_paper.status == ExamPaper.Status.IN_PROGRESS:
                force_finish_exam_papers(exam, exam_paper.candidate)
            return Response(error_response(1002, '考场已关闭'))

        # 考试尚未开始
        if now < exam.start_time:
            return Response(error_response(1003, '考试尚未开始'))

        # 试卷尚未生成
        if exam_paper is None:
            return Response(error_response(1006, '试卷尚未生成，请联系管理员生成试卷'))

        if exam_paper.status == ExamPaper.Status.FINISHED:
            return Response(error_response(1004, '已交卷，不可操作'))

        # pending → in_progress
        if exam_paper.status == ExamPaper.Status.PENDING:
            affected = ExamPaper.objects.filter(
                id=exam_paper.id, status=ExamPaper.Status.PENDING
            ).update(status=ExamPaper.Status.IN_PROGRESS, started_at=timezone.now())
            if affected > 0:
                exam_paper.refresh_from_db()
            else:
                exam_paper.refresh_from_db()
                if exam_paper.status == ExamPaper.Status.FINISHED:
                    return Response(error_response(1004, '已交卷，不可操作'))

        # 组装题目数据
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


class PaperStatusView(APIView):
    """
    GET /api/exams/{exam_id}/paper/status/ — 试卷状态
    - 超时自动交卷（答题时长耗尽）
    - 考场关闭自动交卷
    - 返回剩余秒数和已答题数
    """
    authentication_classes = [ExamJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, exam_id, format=None):
        exam_paper = request.auth

        if exam_paper is None:
            return Response(error_response(1006, '试卷尚未生成'))

        now = timezone.now()

        # 考场关闭 → 强制交卷
        if now > exam_paper.exam.end_time and exam_paper.status == ExamPaper.Status.IN_PROGRESS:
            force_finish_exam_papers(exam_paper.exam, exam_paper.candidate)
            exam_paper.refresh_from_db()

        # 答题超时 → 强制交卷
        if exam_paper.status == ExamPaper.Status.IN_PROGRESS and exam_paper.started_at:
            elapsed = (timezone.now() - exam_paper.started_at).total_seconds()
            if elapsed > exam_paper.exam.duration_minutes * 60:
                affected = ExamPaper.objects.filter(
                    id=exam_paper.id, status=ExamPaper.Status.IN_PROGRESS
                ).update(status=ExamPaper.Status.FINISHED, submitted_at=timezone.now())
                if affected > 0:
                    exam_paper.refresh_from_db()
                    grade_paper(exam_paper)

        # 计算剩余时间
        remaining = 0
        if exam_paper.status == ExamPaper.Status.FINISHED:
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


class SubmitAnswerView(APIView):
    """
    POST .../paper-questions/{pq_id}/answer/ — 提交单题答案
    - 兼容 answer / selected_answer 两种字段名
    - 判断题文本→字母映射
    - 答案格式校验
    """
    authentication_classes = [ExamJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, exam_id, pq_id, format=None):
        exam_paper = request.auth
        logger.info('提交答案 | exam_paper_id=%s pq_id=%s data=%s',
                    exam_paper.id if exam_paper else None, pq_id, request.data)

        if exam_paper.status == ExamPaper.Status.FINISHED:
            return Response(error_response(1004, '已交卷，不可继续答题'))

        if exam_paper.status != ExamPaper.Status.IN_PROGRESS:
            return Response(error_response(1009, '当前无进行中的考试'))

        if exam_paper.started_at:
            elapsed = (timezone.now() - exam_paper.started_at).total_seconds()
            if elapsed > exam_paper.exam.duration_minutes * 60:
                return Response(error_response(1007, '考试时间已到，无法提交答案'))

        try:
            epq = ExamPaperQuestion.objects.get(sort_order=pq_id, exam_paper=exam_paper)
        except ExamPaperQuestion.DoesNotExist:
            return Response(error_response(1006, '题目不存在'))

        selected = request.data.get('selected_answer') or request.data.get('answer')

        # 判断题文本→字母映射
        qt_code = epq.question.question_type.code
        if selected is not None and selected != '' and qt_code == 'judgment':
            shuffled_options = epq.shuffled_options
            text_to_letter = {}
            for i, opt in enumerate(shuffled_options):
                opt_text = opt.split('. ', 1)[-1] if '. ' in opt else opt
                text_to_letter[opt_text] = chr(ord('A') + i)

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
                for synonym_group in synonym_map.values():
                    if selected.strip() in synonym_group:
                        for opt_text, letter in text_to_letter.items():
                            if opt_text in synonym_group:
                                selected = letter
                                matched = True
                                break
                        if matched:
                            break

        # 答案格式校验
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

        Answer.objects.update_or_create(
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


class SubmitPaperView(APIView):
    """POST /api/exams/{exam_id}/submit/ — 手动交卷"""
    authentication_classes = [ExamJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, exam_id, format=None):
        exam_paper = request.auth

        if exam_paper.status == ExamPaper.Status.FINISHED:
            return Response(error_response(1004, '已交卷，不可操作'))

        if exam_paper.status != ExamPaper.Status.IN_PROGRESS:
            return Response(error_response(1009, '当前无进行中的考试'))

        affected = ExamPaper.objects.filter(
            id=exam_paper.id, status=ExamPaper.Status.IN_PROGRESS
        ).update(status=ExamPaper.Status.FINISHED, submitted_at=timezone.now())

        if affected == 0:
            exam_paper.refresh_from_db()
            if exam_paper.status == ExamPaper.Status.FINISHED:
                return Response(error_response(1004, '已交卷，不可操作'))
            return Response(error_response(1009, '当前无进行中的考试'))

        exam_paper.refresh_from_db()
        total_score = grade_paper(exam_paper)
        return Response(success_response({'total_score': float(total_score)}))


class ExamResultView(APIView):
    """GET /api/exams/{exam_id}/result/ — 获取成绩"""
    authentication_classes = [ExamJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, exam_id, format=None):
        exam_paper = request.auth

        if exam_paper is None:
            return Response(error_response(1006, '试卷尚未生成'))

        if exam_paper.status != ExamPaper.Status.FINISHED:
            return Response(error_response(1010, '考试尚未结束，无法查看成绩'))

        return Response(success_response({
            'total_score': float(exam_paper.total_score),
            'submitted_at': exam_paper.submitted_at.strftime('%Y-%m-%dT%H:%M:%S'),
        }))