"""
初始化种子数据（T-19 + §13.1）

执行方式：
    python manage.py init_seed_data

初始化内容：
    1. 三种题型（幂等：已存在则跳过）
    2. 超级管理员的默认账号（可选）

可重复执行：
    所有操作使用 get_or_create，重复执行不会产生重复数据
"""
import logging
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

from questions.models import QuestionType

logger = logging.getLogger('exam')


class Command(BaseCommand):
    help = '初始化种子数据：题型、管理员账号等'

    def add_arguments(self, parser):
        """支持可选参数"""
        parser.add_argument(
            '--admin-username',
            type=str,
            default='admin',
            help='超级管理员用户名（默认：admin）',
        )
        parser.add_argument(
            '--admin-password',
            type=str,
            default='admin123',
            help='超级管理员密码（默认：admin123）',
        )
        parser.add_argument(
            '--skip-admin',
            action='store_true',
            help='跳过创建管理员账号',
        )

    def handle(self, *args, **options):
        """
        执行初始化
        """
        self.stdout.write(self.style.NOTICE('=' * 50))
        self.stdout.write(self.style.NOTICE('开始初始化种子数据...'))
        self.stdout.write(self.style.NOTICE('=' * 50))

        # ====== 1. 初始化题型 ======
        self._init_question_types()

        # ====== 2. 初始化管理员账号（可选） ======
        if not options.get('skip_admin'):
            self._init_admin(
                username=options['admin_username'],
                password=options['admin_password'],
            )
        else:
            self.stdout.write(self.style.WARNING('⏭️  跳过管理员账号创建'))

        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('✅ 种子数据初始化完成！'))
        self.stdout.write(self.style.SUCCESS('=' * 50))

    def _init_question_types(self):
        """
        初始化三种基础题型（§13.1 + Q-01/Q-03 确认）

        题型：
            single_choice  单选题   1分/题
            multi_choice   多选题   1分/题
            judgment       判断题   1分/题

        扩展说明（Q-01 确认）：
            如需新增题型（如填空题、简答题），
            直接在 Django Admin 的「题型」表中添加记录即可，
            本命令只负责初始化最基础的三种题型。
        """
        self.stdout.write('\n📚 初始化题型...')

        question_types = [
            {'code': 'single_choice', 'name': '单选题', 'score': 1},
            {'code': 'multi_choice',  'name': '多选题', 'score': 1},
            {'code': 'judgment',      'name': '判断题', 'score': 1},
        ]

        created_count = 0
        existed_count = 0

        for qt_data in question_types:
            obj, created = QuestionType.objects.get_or_create(
                code=qt_data['code'],
                defaults={
                    'name': qt_data['name'],
                    'score': qt_data['score'],
                },
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✅ 已创建题型：{obj.name}（{obj.score}分/题）'
                    )
                )
            else:
                existed_count += 1
                self.stdout.write(
                    f'  ⏭️  题型已存在：{obj.name}（{obj.score}分/题）'
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'\n  ✅ 题型初始化完成：新建 {created_count} 个，'
                f'已存在 {existed_count} 个'
            )
        )

        # 打印统计
        total = QuestionType.objects.count()
        self.stdout.write(f'  📊 当前题型总数：{total} 种')
        for qt in QuestionType.objects.all():
            self.stdout.write(f'      - {qt.name}({qt.code})：{qt.score}分/题')

    def _init_admin(self, username='admin', password='admin123'):
        """
        初始化超级管理员账号（幂等：已存在则跳过）

        首次部署时执行：
            python manage.py init_seed_data

        如果想自定义账号密码：
            python manage.py init_seed_data --admin-username captain --admin-password safePass2026

        如果已通过 createsuperuser 创建了管理员，本命令不会覆盖：
            使用 get_user_model().objects.filter(username=xxx).exists() 检测
        """
        self.stdout.write('\n👤 初始化超级管理员...')

        User = get_user_model()

        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING(
                    f'  ⏭️  管理员「{username}」已存在，跳过创建'
                )
            )
            return

        try:
            User.objects.create_superuser(
                username=username,
                password=password,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'  ✅ 已创建超级管理员：{username} / {password}'
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    '  ⚠️  请尽快修改初始密码！'
                )
            )
        except Exception as e:
            raise CommandError(f'创建管理员失败：{str(e)}')