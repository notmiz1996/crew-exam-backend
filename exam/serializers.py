# exam/serializers.py

"""
DRF 序列化器（§4.7 API Schema）
"""
import re

from rest_framework import serializers
from .models import Exam, ExamPaper, ExamPaperQuestion, Answer


def success_response(data=None):
    return {'code': 0, 'data': data, 'message': ''}


def error_response(code, message):
    return {'code': code, 'data': None, 'message': message}


class ExamListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exam
        fields = ['id', 'name', 'start_time', 'end_time', 'duration_minutes']


class LoginSerializer(serializers.Serializer):
    id_card = serializers.CharField(max_length=18, min_length=18)

    def validate_id_card(self, value):
        import re
        if not re.match(
            r'^[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])'
            r'(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$', value,
        ):
            raise serializers.ValidationError('身份证号格式不正确')
        return value.upper()


class PaperQuestionSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='sort_order')
    question_type = serializers.CharField(source='question.question_type.code')
    stem = serializers.CharField(source='question.stem')
    options = serializers.JSONField(source='shuffled_options')
    selected_answer = serializers.SerializerMethodField()

    class Meta:
        model = ExamPaperQuestion
        fields = ['id', 'sort_order', 'question_type', 'stem',
                   'options', 'score', 'selected_answer']

    def get_selected_answer(self, obj):
        try:
            return obj.answer.selected_answer
        except Answer.DoesNotExist:
            return None


class PaperSerializer(serializers.ModelSerializer):
    paper_id = serializers.IntegerField(source='id')
    total_count = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    remaining_seconds = serializers.SerializerMethodField()
    questions = PaperQuestionSerializer(source='questions_all', many=True)

    class Meta:
        model = ExamPaper
        fields = ['paper_id', 'status', 'total_count',
                   'duration_seconds', 'remaining_seconds', 'questions']

    def get_total_count(self, obj): return obj.questions.count()
    def get_duration_seconds(self, obj): return obj.exam.duration_minutes * 60

    def get_remaining_seconds(self, obj):
        if not obj.started_at:
            return obj.exam.duration_minutes * 60
        from django.utils import timezone
        elapsed = (timezone.now() - obj.started_at).total_seconds()
        return max(0, int(obj.exam.duration_minutes * 60 - elapsed))


class AnswerSubmitSerializer(serializers.Serializer):
    selected_answer = serializers.CharField(
        allow_null=True, allow_blank=True, required=False, default=None
    )


class PaperStatusSerializer(serializers.ModelSerializer):
    remaining_seconds = serializers.SerializerMethodField()
    answered_count = serializers.SerializerMethodField()
    total_count = serializers.SerializerMethodField()

    class Meta:
        model = ExamPaper
        fields = ['status', 'remaining_seconds', 'answered_count', 'total_count']

    def get_remaining_seconds(self, obj):
        if obj.status == 'finished': return 0
        if not obj.started_at: return obj.exam.duration_minutes * 60
        from django.utils import timezone
        elapsed = (timezone.now() - obj.started_at).total_seconds()
        return max(0, int(obj.exam.duration_minutes * 60 - elapsed))

    def get_answered_count(self, obj):
        return Answer.objects.filter(
            exam_paper_question__exam_paper=obj, selected_answer__isnull=False
        ).count()

    def get_total_count(self, obj): return obj.questions.count()


class ResultSerializer(serializers.ModelSerializer):
    submitted_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S')

    class Meta:
        model = ExamPaper
        fields = ['total_score', 'submitted_at']


class CandidateVerifySerializer(serializers.Serializer):
    """
    考生身份验证入参序列化器
    - 校验身份证号格式
    - 查找考生是否存在
    """
    id_card = serializers.CharField(
        label='身份证号', max_length=18,
        help_text='18位身份证号（末位可为X）',
    )

    def validate_id_card(self, value):
        """校验身份证格式（复用 Model 的正则）"""
        if not re.match(
            r'^[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])'
            r'(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$',
            value,
        ):
            raise serializers.ValidationError('身份证号格式不正确')
        return value.upper()  # 统一转大写 X