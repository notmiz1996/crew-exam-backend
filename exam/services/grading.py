# exam/services/grading.py

"""
自动批改服务（T-06）

三种题型的批改方法（P1-005 使用快照答案）：
  - 单选题 grade_single_choice()
  - 多选题 grade_multi_choice()
  - 判断题 grade_judgment()

批改策略：
  - 所有批改都使用 ExamPaperQuestion.original_answer（组卷时快照的值）
  - 不做文本模糊匹配，严格文本比较
  - 未作答（selected_answer IS NULL）→ is_correct=False, score=0

使用方式：
    from exam.services.grading import grade_paper
    grade_paper(exam_paper)
"""
import logging
from typing import Optional

from exam.models import ExamPaper, Answer, Exam
from exam.utils.answer_mapping import (
    map_letter_to_text,
    map_multiple_letters_to_texts,
)

logger = logging.getLogger('exam')


def grade_paper(exam_paper: ExamPaper) -> float:
    """
    批改整张试卷

    流程（§5.2）：
      1. 遍历该试卷的所有 Answer
      2. 按题型逐题批改
      3. 汇总 total_score
      4. 写入 ExamPaper.total_score

    返回：total_score
    """
    logger.info('开始批改 | exam_paper_id=%s', exam_paper.id)

    answers = list(
        Answer.objects.filter(
            exam_paper_question__exam_paper=exam_paper,
        ).select_related(
            'exam_paper_question__question__question_type',
        )
    )

    total = 0
    grade_count = {'correct': 0, 'wrong': 0, 'unanswered': 0}

    for answer in answers:
        epq = answer.exam_paper_question
        question = epq.question
        qt_code = question.question_type.code

        # ↓↓↓ 新增：每道题都打印状态 ↓↓↓
        logger.info(
            '  批改明细 | answer_id=%s sort_order=%s '
            'selected=%r is_correct=%s qt_code=%s',
            answer.id, epq.sort_order,
            answer.selected_answer, answer.is_correct, qt_code,
        )

        if answer.is_correct is not None:
            logger.info('  → 跳过（is_correct 已存在）')
            total += answer.score
            continue

        # ↓↓↓ 新增：打印选中的答案和原始答案 ↓↓↓
        if qt_code == 'single_choice':
            logger.info('  → 单选题: selected=%s original=%s options=%s',
                        answer.selected_answer, epq.original_answer, epq.shuffled_options)
        elif qt_code == 'judgment':
            logger.info('  → 判断题: selected=%s original=%s options=%s',
                        answer.selected_answer, epq.original_answer, epq.shuffled_options)
        elif qt_code == 'multi_choice':
            logger.info('  → 多选题: selected=%s original=%s options=%s',
                        answer.selected_answer, epq.original_answer, epq.shuffled_options)

        # ── 以下是原有批改逻辑 ──
        if qt_code == 'single_choice':
            is_correct, score = grade_single_choice(answer, epq)
        elif qt_code == 'multi_choice':
            is_correct, score = grade_multi_choice(answer, epq)
        elif qt_code == 'judgment':
            is_correct, score = grade_judgment(answer, epq)
        else:
            logger.warning('未知题型 | answer_id=%s code=%s', answer.id, qt_code)
            is_correct = False
            score = 0

        # ↓↓↓ 新增：打印批改结果 ↓↓↓
        logger.info('  → 批改结果: is_correct=%s score=%s', is_correct, score)

        answer.is_correct = is_correct
        answer.score = score
        answer.save(update_fields=['is_correct', 'score'])

        total += score

        if answer.selected_answer is None:
            grade_count['unanswered'] += 1
        elif is_correct:
            grade_count['correct'] += 1
        else:
            grade_count['wrong'] += 1

    exam_paper.total_score = total
    exam_paper.save(update_fields=['total_score'])

    logger.info(
        '批改完成 | exam_paper_id=%s 总分=%s '
        '正确=%d 错误=%d 未作答=%d',
        exam_paper.id, total,
        grade_count['correct'], grade_count['wrong'],
        grade_count['unanswered'],
    )

    return total


def grade_single_choice(answer: Answer, epq) -> tuple[bool, int]:
    """
    批改单选题
    """
    if answer.selected_answer is None:
        return False, 0

    shuffled_options = epq.shuffled_options
    original_options = epq.question.options
    correct_text = map_letter_to_text(original_options, epq.original_answer)
    selected_text = map_letter_to_text(shuffled_options, answer.selected_answer)

    if correct_text is None or selected_text is None:
        logger.warning('答案映射失败 | answer_id=%s', answer.id)
        return False, 0

    is_correct = selected_text == correct_text
    return is_correct, epq.score if is_correct else 0


def grade_multi_choice(answer: Answer, epq) -> tuple[bool, int]:
    """
    批改多选题
    """
    if answer.selected_answer is None:
        return False, 0

    shuffled_options = epq.shuffled_options
    original_options = epq.question.options

    correct_texts = sorted(
        map_multiple_letters_to_texts(original_options, epq.original_answer)
    )
    selected_texts = sorted(
        map_multiple_letters_to_texts(shuffled_options, answer.selected_answer)
    )

    is_correct = correct_texts == selected_texts
    return is_correct, epq.score if is_correct else 0



def grade_judgment(answer: Answer, epq) -> tuple[bool, int]:
    if answer.selected_answer is None:
        return False, 0

    shuffled_options = epq.shuffled_options
    original_options = epq.question.options
    correct = epq.original_answer  # 可能是 "正确"(文本) 或 "A"(字母)

    # ── 如果 original_answer 是文本（如 "正确"），先转成字母 ──
    if not (len(correct) == 1 and 'A' <= correct.upper() <= 'Z'):
        for i, opt in enumerate(original_options):
            opt_text = opt.split('. ', 1)[-1] if '. ' in opt else opt
            if opt_text == correct:
                correct = chr(ord('A') + i)
                break

    correct_text = map_letter_to_text(original_options, correct)
    selected_text = map_letter_to_text(shuffled_options, answer.selected_answer)

    if correct_text is None or selected_text is None:
        logger.warning('判断题映射失败 | answer_id=%s', answer.id)
        return False, 0

    is_correct = selected_text == correct_text
    return is_correct, epq.score if is_correct else 0


def force_finish_exam_papers(exam, candidate=None):
    """
    强制交卷并批改指定考试中所有进行中的试卷
    使用场景：
    1. 考场关闭时（candidate_login 检测到 now > exam.end_time）
    2. 定时任务（force_finish_expired_exams 管理命令）
    参数：
        exam: Exam 实例
        candidate: 可选，指定考生则只处理该考生的试卷
    返回：强制交卷并批改的试卷数量
    """
    filters = {'exam': exam, 'status': ExamPaper.Status.IN_PROGRESS}
    if candidate is not None:
        filters['candidate'] = candidate

    papers = ExamPaper.objects.filter(**filters).select_related('exam', 'candidate')
    count = 0
    for paper in papers:
        logger.info('强制交卷 | exam_paper_id=%s candidate=%s',
                    paper.id, paper.candidate.name)
        paper.status = ExamPaper.Status.FINISHED
        paper.submitted_at = timezone.now()
        paper.save(update_fields=['status', 'submitted_at'])
        grade_paper(paper)
        count += 1

    if count > 0:
        logger.info('强制交卷完成 | exam=%s count=%d', exam.name, count)
        if candidate is None:  # 第1行：只有批量操作才改
            exam.status = Exam.Status.FINISHED  # 第2行：把考试状态设为"已结束"
            exam.save(update_fields=['status'])  # 第3行：保存到数据库
    return count