# questions/models.py

"""
题库模型：QuestionType（题型）、Chapter（章节树）、Question（题目）
- QuestionType.score 存储每题分值，按题型统一配置（Q-03 确认）
- Chapter 自引用树，level_depth 自动计算，支持任意层级深度（Q-02 确认）
- Question.answer 根据题型不同格式：单选="A", 多选="A,B,C", 判断="正确"/"错误"
"""
from django.db import models
from django.core.exceptions import ValidationError


class QuestionType(models.Model):
    """
    题型表（含分值配置）
    - 分值按题型统一配置（Q-03），组卷时从本表读取 score
    - 种子数据：single_choice(单选题/1分), multi_choice(多选题/1分), judgment(判断题/1分)
    - 可扩展：如需新增题型，直接在本表添加记录即可（Q-01 确认）
    """
    name = models.CharField('题型名称', max_length=32, unique=True)
    code = models.CharField('题型代码', max_length=32, unique=True,
                            help_text='编程用标识，如 single_choice, multi_choice, judgment')
    score = models.IntegerField('每题分值', default=1,
                                help_text='该题型每道题的分值，组卷时使用')

    class Meta:
        verbose_name = '题型'
        verbose_name_plural = '题型'
        ordering = ['id']

    def __str__(self):
        return f'{self.name}（{self.score}分/题）'


class Chapter(models.Model):
    """
    章节表（自引用树结构）
    - 支持任意层级深度（Q-02 确认），level_depth 自动计算
    - 根节点 level_depth=1，每深一层+1
    - 界面展示建议控制在3级以内以保证可用性
    """
    name = models.CharField('章节名称', max_length=128)
    parent = models.ForeignKey(
        'self', verbose_name='父章节', on_delete=models.CASCADE,
        null=True, blank=True, related_name='children',
        help_text='为空时表示根节点（章）'
    )
    sort_order = models.IntegerField('排序', default=0,
                                     help_text='同级章节的排序序号，越小越靠前')
    level_depth = models.IntegerField('层级深度', default=0, editable=False,
                                      help_text='自动计算：根节点=1，每深一层+1')

    class Meta:
        verbose_name = '章节'
        verbose_name_plural = '章节'
        ordering = ['level_depth', 'sort_order', 'id']

    def __str__(self):
        prefix = '　' * (self.level_depth - 1) if self.level_depth > 1 else ''
        return f'{prefix}{self.name}'

    def clean(self):
        """
        自动计算 level_depth + 防止循环引用
        """
        super().clean()
        if self.parent:
            # 防止将自己设为父节点
            if self.parent_id == self.pk:
                raise ValidationError({'parent': '不能将章节自身设为父章节'})
            # 防止循环引用（A→B→C→A）
            if self.pk:
                ancestor = self.parent
                while ancestor:
                    if ancestor.pk == self.pk:
                        raise ValidationError({'parent': '不能形成循环引用'})
                    ancestor = ancestor.parent
            # 自动计算层级深度：父层级+1
            self.level_depth = self.parent.level_depth + 1
        else:
            # 根节点层级=1
            self.level_depth = 1

    def save(self, *args, **kwargs):
        """保存时先校验，再保存"""
        self.clean()
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        """带缩进的展示名称，用于 Admin 下拉选择"""
        return str(self)


class Question(models.Model):
    """
    题目表
    - options: JSON 数组，如 ["A. 选项A", "B. 选项B", "C. 选项C", "D. 选项D"]
    - answer: 根据题型不同格式不同：
      - 单选题(single_choice): "A"（字母）
      - 多选题(multi_choice): "A,B,C"（逗号分隔字母）
      - 判断题(judgment): "正确" 或 "错误"（全文字符串）
    - analysis: 答案解析，可选
    """
    question_type = models.ForeignKey(
        QuestionType, verbose_name='题型', on_delete=models.PROTECT,
        help_text='PROTECT：有题目使用该题型时禁止删除'
    )
    chapter = models.ForeignKey(
        Chapter, verbose_name='所属章节', on_delete=models.PROTECT,
        help_text='PROTECT：有题目引用该章节时禁止删除'
    )
    stem = models.TextField('题干', help_text='题目内容，支持富文本')
    options = models.JSONField('选项列表', default=list,
                               help_text='JSON 数组格式，如 ["A. 选项A", "B. 选项B", ...]')
    answer = models.CharField('正确答案', max_length=512,
                              help_text='单选="A", 多选="A,B,C", 判断="正确"/"错误"')
    analysis = models.TextField('答案解析', blank=True, null=True,
                                help_text='可选，考试后展示给考生')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '题目'
        verbose_name_plural = '题目'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['question_type', 'chapter'],
                         name='idx_questions_type_chapter'),
        ]

    def __str__(self):
        stem_short = self.stem[:50] + '...' if len(self.stem) > 50 else self.stem
        return f'[{self.question_type.name}] {stem_short}'

    def clean(self):
        """
        校验答案格式是否符合题型要求
        """
        super().clean()
        if not self.question_type_id:
            return
        qt = self.question_type
        if qt.code == 'single_choice':
            if not (len(self.answer) == 1 and self.answer.isascii() and self.answer.isalpha()):
                raise ValidationError({'answer': '单选题答案必须是单个字母（如 A、B、C）'})
        elif qt.code == 'multi_choice':
            parts = [p.strip() for p in self.answer.split(',')]
            for p in parts:
                if not (len(p) == 1 and p.isascii() and p.isalpha()):
                    raise ValidationError({'answer': '多选题答案格式错误，应为逗号分隔的字母（如 A,B,C）'})
        elif qt.code == 'judgment':
            if self.answer not in ('正确', '错误'):
                raise ValidationError({'answer': '判断题答案只能是"正确"或"错误"'})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)