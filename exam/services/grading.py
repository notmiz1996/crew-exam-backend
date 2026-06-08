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

from exam.models import ExamPaper, Answer
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
# def grade_judgment(answer: Answer, epq) -> tuple[bool, int]:
#     """
#     批改判断题
#     """
#     if answer.selected_answer is None:
#         return False, 0
#
#     shuffled_options = epq.shuffled_options
#     original_options = epq.question.options
#
#     correct_text = map_letter_to_text(original_options, epq.original_answer)
#     selected_text = map_letter_to_text(shuffled_options, answer.selected_answer)
#
#     if correct_text is None or selected_text is None:
#         logger.warning('判断题映射失败 | answer_id=%s', answer.id)
#         return False, 0
#
#     is_correct = selected_text == correct_text
#     return is_correct, epq.score if is_correct else 0