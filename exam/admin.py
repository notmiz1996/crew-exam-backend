# exam/admin.py

"""
考试核心 Admin 配置（T-03 + T-04）
- Exam：基本信息 Tab + 出题规则内联 + 考生名单内联 + 批量导入
- Candidate：搜索
- ExamPaper：详情页展示完整作答明细
- 已组卷考试只读保护（P1-004）
"""
from django.contrib import admin
from django import forms
from django.shortcuts import redirect
from django.urls import reverse, path
from django.shortcuts import render
from django.contrib import messages
from django.http import HttpResponseRedirect

from .models import (
    Exam, QuestionRule, Candidate, ExamCandidate,
    ExamPaper, ExamPaperQuestion, Answer
)

from .services.exam_import import process_exam_import

# ─── 批量导入依赖 ─────────────────────────────
try:
    import openpyxl
    from openpyxl.utils import get_column_letter
except ImportError:
    openpyxl = None


class QuestionRuleInline(admin.TabularInline):
    model = QuestionRule
    extra = 1
    min_num = 1
    verbose_name = '出题规则'
    verbose_name_plural = '出题规则'
    fields = ('chapter', 'question_type', 'question_count')
    autocomplete_fields = ['chapter', 'question_type']


class ExamCandidateInline(admin.TabularInline):
    model = ExamCandidate
    extra = 0
    can_delete = False
    verbose_name = '考生'
    verbose_name_plural = '已导入考生'
    fields = ('candidate', 'exam_paper', 'created_at')
    readonly_fields = ('exam_paper', 'created_at')
    autocomplete_fields = ['candidate']

    def has_add_permission(self, request, obj=None):
        return False


# ═══════════════════════════════════════════════
# Exam Admin — 考试管理 + 批量导入
# ═══════════════════════════════════════════════

@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    change_list_template = 'admin/exam/exam/change_list.html'

    list_display = ('name', 'start_time', 'end_time', 'duration_minutes',
                    'total_questions', 'total_score', 'candidate_count', 'created_at')
    list_filter = ('start_time',)
    search_fields = ('name',)
    date_hierarchy = 'start_time'
    inlines = [QuestionRuleInline, ExamCandidateInline]

    fieldsets = (
        ('基本信息', {
            'fields': ('name', ('start_time', 'end_time'), ('duration_minutes',),
                       ('total_questions', 'total_score')),
        }),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'import-exams/',
                self.admin_site.admin_view(self.import_exams_view),
                name='exam_exam_import',
            ),
        ]
        return custom_urls + urls

    def import_exams_view(self, request):
        """批量导入考试：上传 xlsx → 交 process_exam_import 处理"""
        context = {
            'title': '批量导入考试',
            'opts': self.model._meta,
            'has_change_permission': self.has_change_permission(request),
            'site_header': self.admin_site.site_header,
            'site_title': self.admin_site.site_title,
        }

        if openpyxl is None:
            messages.error(request, '缺少 openpyxl 库。请运行: pip install openpyxl')
            return render(request, 'admin/exam/exam/import_exams.html', context)

        if request.method == 'POST':
            excel_file = request.FILES.get('excel_file')
            if not excel_file:
                messages.error(request, '请选择一个 xlsx 文件上传')
                return render(request, 'admin/exam/exam/import_exams.html', context)

            if not excel_file.name.endswith(('.xlsx', '.xls')):
                messages.error(request, '仅支持 .xlsx 格式文件')
                return render(request, 'admin/exam/exam/import_exams.html', context)

            try:
                wb = openpyxl.load_workbook(excel_file)
            except Exception as e:
                messages.error(request, f'文件读取失败: {e}')
                return render(request, 'admin/exam/exam/import_exams.html', context)

            result = process_exam_import(wb, request)

            if not result.get('success'):
                return render(request, 'admin/exam/exam/import_exams.html', context)

            parts = []
            if result['exam_created']:
                parts.append(f'考试: ✅ {result["exam_created"]} 个')
            if result['exam_skipped']:
                parts.append(f'考试: ⏭️ {result["exam_skipped"]} 个已存在跳过')
            if result['rule_created']:
                parts.append(f'出题规则: ✅ {result["rule_created"]} 条')
            if result['rule_skipped']:
                parts.append(f'出题规则: ⏭️ {result["rule_skipped"]} 条跳过')
            if result['candidate_added']:
                parts.append(f'考生: ✅ {result["candidate_added"]} 人')
            if result['candidate_skipped']:
                parts.append(f'考生: ⏭️ {result["candidate_skipped"]} 人跳过')

            if parts:
                messages.success(request, ' | '.join(parts))
            else:
                messages.warning(request, '没有新的数据被导入，请检查文件内容')

            return HttpResponseRedirect(reverse('admin:exam_exam_changelist'))

        return render(request, 'admin/exam/exam/import_exams.html', context)

    # ── 统计考生人数 ──
    def candidate_count(self, obj):
        return obj.exam_candidates.count()

    candidate_count.short_description = '考生人数'

    # ── 保存校验（含子章节递归查询，与组卷逻辑一致） ──
    def save_model(self, request, obj, form, change):
        from questions.models import Question

        super().save_model(request, obj, form, change)

        rules = list(obj.question_rules.all().select_related('chapter', 'question_type'))

        if len(rules) == 0:
            messages.error(request, '请先添加至少一条出题规则')
            return

        total_from_rules = sum(r.question_count for r in rules)
        total_score_from_rules = sum(
            r.question_count * r.question_type.score for r in rules
        )

        has_error = False

        # ── 校验总题数 ──
        if total_from_rules != obj.total_questions:
            has_error = True
            messages.error(
                request,
                f'❌ 总题数不一致：考试设置 {obj.total_questions} 题，'
                f'但出题规则合计 {total_from_rules} 题'
                f'（差额 {total_from_rules - obj.total_questions} 题）'
            )

        # ── 校验总分 ──
        if total_score_from_rules != obj.total_score:
            has_error = True
            messages.error(
                request,
                f'❌ 总分不一致：考试设置 {obj.total_score} 分，'
                f'但出题规则合计 {total_score_from_rules} 分'
                f'（差额 {total_score_from_rules - obj.total_score} 分）'
            )

        # ── 逐条校验：递归查找章节及所有子章节的题目（与 paper_generator 一致） ──
        shortage_rules = []
        for r in rules:
            actual_count = self._count_questions_in_chapter_tree(
                r.chapter, r.question_type
            )
            if actual_count < r.question_count:
                shortage_rules.append(
                    f'章节「{r.chapter.name}」+ {r.question_type.name}：'
                    f'需要 {r.question_count} 题，题库（含子章节）仅有 {actual_count} 题，'
                    f'缺少 {r.question_count - actual_count} 题'
                )

        if shortage_rules:
            has_error = True
            for msg in shortage_rules:
                messages.warning(request, f'⚠️ {msg}')

        if has_error:
            return

        messages.success(request, '✅ 考试保存成功，待考生名单确认后触发组卷')

    # ── 递归获取章节及其所有子章节的题目数量（与 paper_generator 一致） ──
    def _count_questions_in_chapter_tree(self, chapter, question_type):
        """统计指定章节及其所有子章节中某题型的题目数量"""
        from questions.models import Question, Chapter as ChapterModel

        def _get_descendant_ids(ch):
            ids = {ch.id}
            children = ChapterModel.objects.filter(parent=ch).only('id')
            for child in children:
                ids.update(_get_descendant_ids(child))
            return ids

        chapter_ids = _get_descendant_ids(chapter)
        return Question.objects.filter(
            chapter_id__in=chapter_ids,
            question_type=question_type,
        ).count()


@admin.register(QuestionRule)
class QuestionRuleAdmin(admin.ModelAdmin):
    list_display = ('exam', 'chapter', 'question_type', 'question_count', 'rule_score')
    list_filter = ('exam',)
    search_fields = ('exam__name',)

    def rule_score(self, obj):
        return obj.question_count * obj.question_type.score
    rule_score.short_description = '小计分数'


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('name', 'id_card', 'created_at')
    search_fields = ('name', 'id_card')
    actions = []


class AnswerInline(admin.StackedInline):
    model = Answer
    extra = 0
    can_delete = False
    fields = ('selected_answer', 'is_correct', 'score', 'answered_at')
    readonly_fields = ('selected_answer', 'is_correct', 'score', 'answered_at')

    def has_add_permission(self, request, obj=None):
        return False


class ExamPaperQuestionInline(admin.TabularInline):
    model = ExamPaperQuestion
    extra = 0
    can_delete = False
    fields = ('sort_order', 'question', 'shuffled_options', 'original_answer', 'score')
    readonly_fields = ('sort_order', 'question', 'shuffled_options', 'original_answer', 'score')
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ExamPaper)
class ExamPaperAdmin(admin.ModelAdmin):
    list_display = ('id', 'exam', 'candidate', 'status', 'total_score',
                    'started_at', 'submitted_at')
    list_filter = ('status', 'exam')
    search_fields = ('candidate__name', 'candidate__id_card')
    inlines = [ExamPaperQuestionInline]
    readonly_fields = ('exam', 'candidate', 'status', 'total_score',
                       'started_at', 'submitted_at')
    fieldsets = (
        ('试卷信息', {
            'fields': ('exam', 'candidate', 'status',
                       ('total_score',), ('started_at', 'submitted_at')),
        }),
        ('统计摘要', {
            'fields': ('answer_summary',),
            'description': '作答统计（自动计算）',
        }),
    )

    def answer_summary(self, obj):
        answers = Answer.objects.filter(exam_paper_question__exam_paper=obj)
        total = answers.count()
        answered = answers.exclude(selected_answer=None).count()
        correct = answers.filter(is_correct=True).count()
        wrong = answers.filter(is_correct=False).count()
        unanswered = answers.filter(selected_answer=None).count()
        return f'总题数：{total} ｜ 已作答：{answered} ｜ 正确：{correct} ｜ 错误：{wrong} ｜ 未作答：{unanswered}'
    answer_summary.short_description = '作答统计'

    def has_add_permission(self, request, obj=None):
        return False