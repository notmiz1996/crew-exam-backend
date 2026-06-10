# exam/management/commands/setup_schedule.py
"""
管理命令：注册 Django-Q 定时任务
只需执行一次，后续 Django-Q 会自动按周期执行

使用方式：
    python manage.py setup_schedule           # 注册（默认每 5 分钟）
    python manage.py setup_schedule --minutes=10  # 自定义间隔
"""
from django.core.management.base import BaseCommand
from django_q.models import Schedule
from django_q.tasks import schedule


class Command(BaseCommand):
    help = '注册 Django-Q 定时任务：自动检查过期考试并强制交卷批改'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes', type=int, default=5,
            help='执行间隔（分钟），默认 5 分钟',
        )

    def handle(self, *args, **options):
        interval = options['minutes']

        # 避免重复注册：先删除同名旧任务
        Schedule.objects.filter(name='auto-finish-expired').delete()

        # 注册新定时任务
        schedule(
            'exam.tasks.auto_finish_expired_exams',  # 任务函数路径
            name='auto-finish-expired',              # 任务名称
            schedule_type=Schedule.MINUTES,          # 按分钟
            minutes=interval,                        # 间隔
            repeats=-1,                              # -1 表示无限重复
        )

        self.stdout.write(self.style.SUCCESS(
            f'✅ 定时任务已注册：每 {interval} 分钟执行一次自动批改\n'
            f'   Admin 查看路径：Django Q → Scheduled Tasks\n'
            f'   如需修改间隔，直接在 Admin 页面修改分钟数即可'
        ))