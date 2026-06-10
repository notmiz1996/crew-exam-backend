# exam/tasks.py
"""
Django-Q 异步任务
用于定时检查过期考试并自动强制交卷批改
"""
import logging
from django.utils import timezone
from .models import Exam
from .services.grading import force_finish_exam_papers

logger = logging.getLogger('exam')


def auto_finish_expired_exams():
    """
    Django-Q 定时任务：查找所有已过期且仍有进行中试卷的考试，强制交卷批改
    由 Schedule 对象每 5 分钟触发一次
    """
    now = timezone.now()
    expired_exams = Exam.objects.filter(end_time__lt=now)
    total_papers = 0
    total_exams = 0

    for exam in expired_exams:
        count = force_finish_exam_papers(exam)
        if count > 0:
            total_papers += count
            total_exams += 1

    logger.info(
        'Django-Q 自动批改 | exams=%d papers=%d',
        total_exams, total_papers,
    )
    return f'已处理 {total_exams} 场考试, {total_papers} 份试卷'