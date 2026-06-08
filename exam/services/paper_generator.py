# exam/services/paper_generator.py

"""
自动组卷服务（T-05）
- 按出题规则从题库抽题（含子章节递归）
- 每位考生独立打乱题目顺序 + 选项顺序
- 使用 bulk_create 批量写入（100考生×100题 ≈ 1万条记录）
- 全部在 @transaction.atomic 中执行，失败则完整回滚
- 答案快照（P1-005）：组卷时快照正确答案到 original_answer
"""
import random
import logging
from collections import defaultdict

from django.db import transaction
from django.db.models import Prefetch

from questions.models import Question, Chapter, QuestionType
from exam.models import (
    Exam, ExamCandidate, ExamPaper,
    ExamPaperQuestion, Answer,
)

logger = logging.getLogger('exam')


class PaperGenerationError(Exception):
    """
    组卷异常
    携带用户可读的错误消息，Admin 界面直接展示给管理员
    """
    pass


class PaperGenerator:
    """
    自动组卷器

    用法：
        generator = PaperGenerator(exam)
        generator.generate()

    流程（§5.1）：
        Step 1: 按规则抽取题目（random.sample）
        Step 2: 为每位考生打乱题目顺序 + 选项顺序
        Step 3: bulk_create 批量写入 ExamPaper + ExamPaperQuestion + Answer
        Step 4: 关联 ExamPaper 到 ExamCandidate
    """

    def __init__(self, exam: Exam):
        self.exam = exam

    @transaction.atomic
    def generate(self):
        """
        执行组卷（事务内原子操作）
        失败则回滚全部，考试保持未组卷状态
        """
        logger.info('开始组卷 | exam_id=%s name=%s', self.exam.id, self.exam.name)

        # Step 0: 校验前置条件
        self._validate()

        # Step 1: 按规则抽取题目池
        question_pool = self._collect_questions()

        # 获取所有考生
        candidates = list(
            self.exam.exam_candidates
            .select_related('candidate')
            .all()
        )

        # Step 2: 批量创建 ExamPaper
        papers = [
            ExamPaper(exam=self.exam, candidate=ec.candidate)
            for ec in candidates
        ]
        created_papers = ExamPaper.objects.bulk_create(papers)
        logger.info('ExamPaper 创建完成 | count=%d', len(created_papers))

        # Step 3: 为每份试卷创建 ExamPaperQuestion + Answer
        all_epqs = []

        for paper in created_papers:
            # 3a. 题目顺序打乱（每人独立）
            shuffled_pool = list(question_pool)
            random.shuffle(shuffled_pool)

            for idx, (question, score) in enumerate(shuffled_pool):
                # 3b. 选项顺序打乱（每道题独立）
                original_options = list(question.options)
                shuffled_options = list(original_options)
                random.shuffle(shuffled_options)

                all_epqs.append(ExamPaperQuestion(
                    exam_paper=paper,
                    question=question,
                    sort_order=idx + 1,
                    shuffled_options=shuffled_options,
                    score=score,
                    original_answer=question.answer,
                ))

        created_epqs = ExamPaperQuestion.objects.bulk_create(all_epqs)
        logger.info('ExamPaperQuestion 创建完成 | count=%d', len(created_epqs))

        # Step 4: 为每个 ExamPaperQuestion 创建 Answer（空答案）
        answers = [
            Answer(exam_paper_question=epq)
            for epq in created_epqs
        ]
        Answer.objects.bulk_create(answers)
        logger.info('Answer 创建完成 | count=%d', len(answers))

        # Step 5: 关联 ExamCandidate.exam_paper
        for paper, ec in zip(created_papers, candidates):
            ec.exam_paper = paper
        ExamCandidate.objects.bulk_update(candidates, ['exam_paper'])
        logger.info('ExamCandidate 关联完成 | count=%d', len(candidates))

        logger.info(
            '组卷完成 | exam_id=%s 考生数=%d 总题数=%d',
            self.exam.id, len(candidates), len(question_pool),
        )

    def _validate(self):
        """
        校验组卷前置条件
        """
        rules = list(self.exam.question_rules.select_related(
            'chapter', 'question_type'
        ).all())
        if not rules:
            raise PaperGenerationError(
                f'考试「{self.exam.name}」尚未配置出题规则，无法组卷'
            )

        candidate_count = self.exam.exam_candidates.count()
        if candidate_count == 0:
            raise PaperGenerationError(
                f'考试「{self.exam.name}」考生名单为空，请先导入考生'
            )

        total_from_rules = 0
        score_from_rules = 0
        errors = []

        for rule in rules:
            total_from_rules += rule.question_count
            score_from_rules += rule.question_count * rule.question_type.score

            chapter_ids = self._get_descendant_chapter_ids(rule.chapter)
            actual_count = Question.objects.filter(
                chapter_id__in=chapter_ids,
                question_type=rule.question_type,
            ).count()

            if actual_count < rule.question_count:
                errors.append(
                    f'章节「{rule.chapter.name}」+ '
                    f'题型「{rule.question_type.name}」：'
                    f'需要 {rule.question_count} 题，题库仅有 {actual_count} 题，'
                    f'缺少 {rule.question_count - actual_count} 题'
                )

        if errors:
            raise PaperGenerationError(
                '题库存量不足，无法组卷：\n' + '\n'.join(errors)
            )

        if total_from_rules != self.exam.total_questions:
            raise PaperGenerationError(
                f'总题数不一致：规则抽题总数 {total_from_rules} ≠ '
                f'考试设定 {self.exam.total_questions}'
            )

        if score_from_rules != self.exam.total_score:
            raise PaperGenerationError(
                f'总分不一致：规则计算总分 {score_from_rules} ≠ '
                f'考试设定 {self.exam.total_score}'
            )

    def _get_descendant_chapter_ids(self, chapter):
        """
        递归获取指定章节及其所有后代章节的 ID 集合
        """
        ids = {chapter.id}
        children = Chapter.objects.filter(parent=chapter).only('id')
        for child in children:
            ids.update(self._get_descendant_chapter_ids(child))
        return ids

    def _collect_questions(self):
        """
        按出题规则抽取题目池
        返回 [(question, score), ...] 列表
        """
        rules = self.exam.question_rules.select_related(
            'chapter', 'question_type'
        ).all()

        pool = []

        for rule in rules:
            chapter_ids = self._get_descendant_chapter_ids(rule.chapter)
            questions = list(Question.objects.filter(
                chapter_id__in=chapter_ids,
                question_type=rule.question_type,
            ))
            sampled = random.sample(questions, rule.question_count)
            for q in sampled:
                pool.append((q, rule.question_type.score))

        return pool