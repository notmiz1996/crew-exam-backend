# exam/models.py

"""
考试核心模型（T-03 + T-04 合并输出）
包含全部 7 张表：
- Exam / QuestionRule / Candidate / ExamCandidate（T-03 考试模型）
- ExamPaper / ExamPaperQuestion / Answer（T-04 试卷模型）

为什么合并到一个文件？
  因为 ExamPaper 外键引用 Exam 和 Candidate，放在同一文件避免循环导入，
  且 makemigrations 只需一次，结构更清晰。
"""
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


# ============================================================
# T-03 · 考试模型
# ============================================================

class Exam(models.Model):
    """
    考试表
    - 无显式状态字段，时间驱动判断（§3.2）
    - 保存时自动触发出题规则校验（T-03.5）
    - 已组卷考试设为只读（P1-004）
    """
    name = models.CharField('考试名称', max_length=128)
    start_time = models.DateTimeField('开始时间')
    end_time = models.DateTimeField('结束时间')
    duration_minutes = models.IntegerField('考试时长（分钟）',
                                           help_text='考生实际答题时长，不得大于考试窗口')
    total_questions = models.IntegerField('总题数', default=100)
    total_score = models.IntegerField('总分', default=100)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '考试'
        verbose_name_plural = '考试'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def clean(self):
        """校验时间逻辑"""
        super().clean()
        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                raise ValidationError('结束时间必须晚于开始时间')
            window_minutes = (self.end_time - self.start_time).total_seconds() / 60
            if self.duration_minutes > window_minutes:
                raise ValidationError({
                    'duration_minutes': f'考试时长({self.duration_minutes}分钟)'
                    f'不能超过考试窗口({int(window_minutes)}分钟)'
                })

    def save(self, *args, **kwargs):
        """保存时先校验，再保存"""
        self.clean()
        super().save(*args, **kwargs)


class QuestionRule(models.Model):
    """
    出题规则表
    - 每条规则：从某章节抽取某题型 N 道题
    - 分值统一从 QuestionType.score 读取，不在此处配置（Q-03）
    - 同一考试中，(chapter, question_type) 组合唯一
    """
    exam = models.ForeignKey(
        Exam, verbose_name='所属考试', on_delete=models.CASCADE,
        related_name='question_rules'
    )
    chapter = models.ForeignKey(
        'questions.Chapter', verbose_name='出题章节',
        on_delete=models.PROTECT
    )
    question_type = models.ForeignKey(
        'questions.QuestionType', verbose_name='题型',
        on_delete=models.PROTECT
    )
    question_count = models.IntegerField('抽题数量',
                                         help_text='从该章节该题型抽取的题目数')

    class Meta:
        verbose_name = '出题规则'
        verbose_name_plural = '出题规则'
        unique_together = ('exam', 'chapter', 'question_type')
        ordering = ['exam', 'chapter', 'question_type']

    def __str__(self):
        return f'{self.exam.name} - {self.chapter.name} - {self.question_type.name} x{self.question_count}'

    def clean(self):
        """抽题数量不能为负数"""
        super().clean()
        if self.question_count is not None and self.question_count < 0:
            raise ValidationError({'question_count': '抽题数量不能为负数'})


class Candidate(models.Model):
    """
    考生表
    - 身份证号唯一约束，是登录凭据（无密码）
    - 姓名必填（Q-04 确认）
    """
    id_card = models.CharField('身份证号', max_length=18, unique=True,
                               help_text='18位身份证号，登录凭证')
    name = models.CharField('姓名', max_length=64)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '考生'
        verbose_name_plural = '考生'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['id_card'], name='idx_candidates_id_card'),
        ]

    def __str__(self):
        return f'{self.name}({self.id_card})'

    def clean(self):
        """身份证号格式校验（18位，最后一位可为X）"""
        super().clean()
        if self.id_card:
            import re
            if not re.match(r'^[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]$', self.id_card):
                raise ValidationError({'id_card': '身份证号格式不正确'})


class ExamCandidate(models.Model):
    """
    考试-考生关联表
    - 记录哪些考生参加了哪场考试
    - exam_paper_id 在组卷后关联到对应的试卷
    - (exam, candidate) 唯一：同一考生不能重复参加同一考试
    """
    exam = models.ForeignKey(
        Exam, verbose_name='考试', on_delete=models.CASCADE,
        related_name='exam_candidates'
    )
    candidate = models.ForeignKey(
        Candidate, verbose_name='考生', on_delete=models.CASCADE,
        related_name='exam_candidates'
    )
    exam_paper = models.OneToOneField(
        'ExamPaper', verbose_name='试卷', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
        help_text='组卷后自动关联，可为空'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '考试考生'
        verbose_name_plural = '考试考生'
        unique_together = ('exam', 'candidate')
        ordering = ['exam', 'candidate']

    def __str__(self):
        return f'{self.exam.name} - {self.candidate.name}'


# ============================================================
# T-04 · 试卷模型
# ============================================================

class ExamPaper(models.Model):
    """
    试卷表（状态机：pending → in_progress → finished §3.1）
    """
    class Status(models.TextChoices):
        PENDING = 'pending', '未开始'
        IN_PROGRESS = 'in_progress', '进行中'
        FINISHED = 'finished', '已交卷'

    exam = models.ForeignKey(
        Exam, verbose_name='考试', on_delete=models.CASCADE,
        related_name='exam_papers'
    )
    candidate = models.ForeignKey(
        Candidate, verbose_name='考生', on_delete=models.CASCADE,
        related_name='exam_papers'
    )
    status = models.CharField('状态', max_length=16,
                              choices=Status.choices,
                              default=Status.PENDING)
    total_score = models.DecimalField('总分', max_digits=10, decimal_places=2,
                                      default=0)
    started_at = models.DateTimeField('开始答题时间', null=True, blank=True)
    submitted_at = models.DateTimeField('交卷时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '试卷'
        verbose_name_plural = '试卷'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['exam', 'candidate'],
                         name='idx_papers_exam_candidate'),
            models.Index(fields=['status'], name='idx_papers_status'),
        ]

    def __str__(self):
        return f'{self.exam.name} - {self.candidate.name}({self.status})'


class ExamPaperQuestion(models.Model):
    """
    试卷题目明细表（组卷时生成，含答案快照）
    - shuffled_options：打乱后的选项列表
    - score：组卷时从 QuestionType.score 读取并快照
    - original_answer：组卷时快照的正确答案（P1-005）
    """
    exam_paper = models.ForeignKey(
        ExamPaper, verbose_name='所属试卷', on_delete=models.CASCADE,
        related_name='questions'
    )
    question = models.ForeignKey(
        'questions.Question', verbose_name='原始题目',
        on_delete=models.PROTECT
    )
    sort_order = models.IntegerField('排序序号')
    shuffled_options = models.JSONField('打乱后的选项')
    score = models.IntegerField('本题分值', default=1,
                                help_text='组卷时从 QuestionType.score 读取并快照')
    original_answer = models.CharField('快照正确答案', max_length=512,
                                       help_text='组卷时快照的正确答案（P1-005）')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '试卷题目'
        verbose_name_plural = '试卷题目'
        ordering = ['exam_paper', 'sort_order']
        indexes = [
            models.Index(fields=['exam_paper'], name='idx_epq_paper'),
        ]

    def __str__(self):
        return f'第{self.sort_order}题 - {self.exam_paper}'


class Answer(models.Model):
    """
    作答记录表
    - selected_answer: NULL=未作答
    - is_correct: NULL=未批改
    """
    exam_paper_question = models.OneToOneField(
        ExamPaperQuestion, verbose_name='试卷题目',
        on_delete=models.CASCADE, related_name='answer'
    )
    selected_answer = models.CharField('考生答案', max_length=512,
                                       null=True, blank=True)
    is_correct = models.BooleanField('是否正确', null=True, blank=True)
    score = models.IntegerField('得分', default=0)
    answered_at = models.DateTimeField('作答时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '作答记录'
        verbose_name_plural = '作答记录'

    def __str__(self):
        status = '未作答' if self.selected_answer is None else self.selected_answer
        return f'{self.exam_paper_question} - {status}'

    def _check_readonly_before_save(self):
        """
        已组卷考试禁止修改（P1-004 模型层只读保护）
        检查条件：只要该考试存在任何 ExamPaper 记录，即视为已组卷
        """
        if self.pk is None:
            return  # 新建考试，允许保存

        if ExamPaper.objects.filter(exam=self).exists():
            raise ValidationError(
                f'考试「{self.name}」已组卷，不允许修改基本信息。'
                '如需修改请先清空试卷记录。'
            )

    def save(self, *args, **kwargs):
        """保存时先校验+只读检查，再保存"""
        self.clean()
        self._check_readonly_before_save()
        super().save(*args, **kwargs)