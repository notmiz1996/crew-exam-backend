# exam/services/exam_import.py

"""
考试批量导入核心逻辑
- 包含三个 Sheet 的解析与数据库写入
- 被 exam/admin.py 中 ExamAdmin.import_exams_view 调用
"""
from datetime import datetime

from django.contrib import messages

from exam.models import Exam, QuestionRule, Candidate, ExamCandidate
from questions.models import Chapter, QuestionType


def process_exam_import(wb, request):
    """
    处理考试批量导入主逻辑
    参数:
        wb: openpyxl.Workbook 对象（已打开）
        request: HttpRequest（用于 messages 反馈）
    返回:
        dict: {success: bool, exam_created: int, ...} 或 {'success': False}
    """
    sheet_names = wb.sheetnames
    required_sheets = ['考试基本信息', '出题规则', '考生名单']
    missing = [s for s in required_sheets if s not in sheet_names]
    if missing:
        messages.error(
            request,
            f'缺少必要工作表: {", ".join(missing)}。'
            f'当前工作表: {", ".join(sheet_names)}'
        )
        return {'success': False}

    # ── 预加载题型缓存 ──
    qt_cache = {qt.name: qt for qt in QuestionType.objects.all()}

    # ═══════════════════════════════════════════
    # Sheet 1：考试基本信息
    # ══════════════════════════════════════════
    ws1 = wb['考试基本信息']
    exam_rows = list(ws1.iter_rows(values_only=True))
    exam_created = 0
    exam_skipped = 0
    exam_name_map = {}

    if len(exam_rows) < 2:
        messages.error(request, '「考试基本信息」工作表中没有数据行（仅有表头）')
        return {'success': False}

    exam_header = [str(c or '').strip() for c in exam_rows[0]]
    if '考试名称' not in exam_header or '开始时间' not in exam_header:
        messages.error(
            request,
            f'「考试基本信息」表头不符合要求，必须包含：考试名称、开始时间。'
            f'当前表头: {", ".join(exam_header)}'
        )
        return {'success': False}

    exam_col_idx = {}
    for col in ['考试名称', '开始时间', '结束时间', '考试时长(分钟)', '总题数', '总分']:
        if col in exam_header:
            exam_col_idx[col] = exam_header.index(col)

    time_formats = [
        '%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M',
        '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S',
        '%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S',
    ]

    for row_idx, row in enumerate(exam_rows[1:], start=2):
        if all(c is None or str(c).strip() == '' for c in row):
            continue

        try:
            name = str(row[exam_col_idx['考试名称']] or '').strip()
            if not name:
                exam_skipped += 1
                continue

            if Exam.objects.filter(name=name).exists():
                exam_name_map[name] = Exam.objects.get(name=name)
                exam_skipped += 1
                continue

            start_time_str = str(row[exam_col_idx.get('开始时间', -1)] or '').strip()
            end_time_str = str(row[exam_col_idx.get('结束时间', -1)] or '').strip()
            if not start_time_str:
                exam_skipped += 1
                continue

            start_time = None
            for fmt in time_formats:
                try:
                    start_time = datetime.strptime(start_time_str, fmt)
                    break
                except ValueError:
                    continue
            if not start_time:
                exam_skipped += 1
                continue

            end_time = None
            if end_time_str:
                for fmt in time_formats:
                    try:
                        end_time = datetime.strptime(end_time_str, fmt)
                        break
                    except ValueError:
                        continue

            def _safe_int(val, default=0):
                s = str(val or '0').strip().replace('.', '', 1)
                return int(float(str(val or '0').strip())) if s.isdigit() else default

            duration_minutes = _safe_int(row[exam_col_idx.get('考试时长(分钟)', -1)], 120)
            total_questions = _safe_int(row[exam_col_idx.get('总题数', -1)], 100)
            total_score = _safe_int(row[exam_col_idx.get('总分', -1)], 100)

            exam = Exam.objects.create(
                name=name,
                start_time=start_time,
                end_time=end_time or start_time,
                duration_minutes=duration_minutes,
                total_questions=total_questions,
                total_score=total_score,
            )
            exam_name_map[name] = exam
            exam_created += 1

        except Exception:
            exam_skipped += 1
            continue

    default_exam = list(exam_name_map.values())[-1] if exam_name_map else None
    if default_exam is None:
        messages.error(request, '「考试基本信息」未创建任何考试，请检查文件内容')
        return {'success': False}

    # ═══════════════════════════════════════════
    # Sheet 2：出题规则（自动识别格式）
    # ══════════════════════════════════════════
    ws2 = wb['出题规则']
    rule_rows = list(ws2.iter_rows(values_only=True))
    rule_created = 0
    rule_skipped = 0

    if len(rule_rows) >= 2:
        rule_header = [str(c or '').strip() for c in rule_rows[0]]
        is_pivot = '名称' in rule_header and any(
            t in rule_header for t in ['单选题', '多选题', '判断题']
        )
        is_old = '题型' in rule_header and '抽题数量' in rule_header

        if is_pivot:
            # ── 透视表格式 ──
            type_cols = {}
            for col_name in ['单选题', '多选题', '判断题']:
                if col_name in rule_header:
                    type_cols[col_name] = rule_header.index(col_name)

            for row_idx, row in enumerate(rule_rows[1:], start=2):
                if all(c is None or str(c).strip() == '' for c in row):
                    continue

                chapter_name = str(row[rule_header.index('名称')] or '').strip()
                if not chapter_name:
                    rule_skipped += 1
                    continue

                try:
                    chapter = Chapter.objects.get(name=chapter_name)
                except Chapter.DoesNotExist:
                    rule_skipped += 1
                    continue

                exam = default_exam
                if '考试名称' in rule_header:
                    en = str(row[rule_header.index('考试名称')] or '').strip()
                    if en in exam_name_map:
                        exam = exam_name_map[en]

                for type_name, col_idx in type_cols.items():
                    raw = str(row[col_idx] or '').strip()
                    if not raw:
                        continue
                    try:
                        count = int(float(raw))
                    except (ValueError, TypeError):
                        continue
                    if count <= 0 or type_name not in qt_cache:
                        continue

                    _, created = QuestionRule.objects.get_or_create(
                        exam=exam,
                        chapter=chapter,
                        question_type=qt_cache[type_name],
                        defaults={'question_count': count},
                    )
                    if created:
                        rule_created += 1

        elif is_old:
            # ── 旧明细表格式 ──
            has_exam_col = '考试名称' in rule_header
            col_idx_map = {}
            if has_exam_col:
                col_idx_map['考试名称'] = rule_header.index('考试名称')
            for col in ['所属章', '所属节', '所属小节', '题型', '抽题数量']:
                if col in rule_header:
                    col_idx_map[col] = rule_header.index(col)

            chapter_cache = {}

            def _get_chapter(zn, jn='', xjn=''):
                k1 = (None, zn)
                if k1 in chapter_cache:
                    zn_node = chapter_cache[k1]
                else:
                    zn_node, _ = Chapter.objects.get_or_create(
                        parent=None, name=zn,
                        defaults={'sort_order': 0, 'level_depth': 1},
                    )
                    chapter_cache[k1] = zn_node
                if not jn:
                    return zn_node
                k2 = (zn_node.pk, jn)
                if k2 in chapter_cache:
                    return chapter_cache[k2]
                jn_node, _ = Chapter.objects.get_or_create(
                    parent=zn_node, name=jn,
                    defaults={'sort_order': 0, 'level_depth': 2},
                )
                chapter_cache[k2] = jn_node
                if not xjn:
                    return jn_node
                k3 = (jn_node.pk, xjn)
                if k3 in chapter_cache:
                    return chapter_cache[k3]
                xjn_node, _ = Chapter.objects.get_or_create(
                    parent=jn_node, name=xjn,
                    defaults={'sort_order': 0, 'level_depth': 3},
                )
                chapter_cache[k3] = xjn_node
                return xjn_node

            for row_idx, row in enumerate(rule_rows[1:], start=2):
                if all(c is None or str(c).strip() == '' for c in row):
                    continue
                try:
                    if has_exam_col:
                        en = str(row[col_idx_map['考试名称']] or '').strip()
                        if not en or en not in exam_name_map:
                            rule_skipped += 1
                            continue
                        exam = exam_name_map[en]
                    else:
                        exam = default_exam

                    zhang = str(row[col_idx_map.get('所属章', -1)] or '').strip()
                    if not zhang:
                        rule_skipped += 1
                        continue
                    jie = str(row[col_idx_map.get('所属节', -1)] or '').strip()
                    xiaojie = str(row[col_idx_map.get('所属小节', -1)] or '').strip()
                    chapter = _get_chapter(zhang, jie, xiaojie)

                    tn = str(row[col_idx_map.get('题型', -1)] or '').strip()
                    if not tn or tn not in qt_cache:
                        rule_skipped += 1
                        continue

                    cs = str(row[col_idx_map.get('抽题数量', -1)] or '0').strip()
                    count = int(float(cs)) if cs.replace('.', '', 1).isdigit() else 0
                    if count <= 0:
                        rule_skipped += 1
                        continue

                    _, created = QuestionRule.objects.get_or_create(
                        exam=exam, chapter=chapter,
                        question_type=qt_cache[tn],
                        defaults={'question_count': count},
                    )
                    if created:
                        rule_created += 1
                except Exception:
                    rule_skipped += 1
                    continue

        else:
            messages.warning(
                request,
                '「出题规则」工作表格式无法识别，跳过规则导入。'
                '支持的格式：透视表（名称+题型列）或明细表（所属章+题型+抽题数量）'
            )

    # ═══════════════════════════════════════════
    # Sheet 3：考生名单
    # ══════════════════════════════════════════
    ws3 = wb['考生名单']
    candidate_rows = list(ws3.iter_rows(values_only=True))
    candidate_added = 0
    candidate_skipped = 0

    if len(candidate_rows) >= 2:
        cand_header = [str(c or '').strip() for c in candidate_rows[0]]
        has_exam_col = '考试名称' in cand_header
        cand_idx = {}
        if has_exam_col:
            cand_idx['考试名称'] = cand_header.index('考试名称')
        for col in ['身份证号', '姓名']:
            if col in cand_header:
                cand_idx[col] = cand_header.index(col)

        if '身份证号' not in cand_idx:
            messages.warning(request, '「考生名单」缺少"身份证号"列，跳过考生导入')
        else:
            for row_idx, row in enumerate(candidate_rows[1:], start=2):
                if all(c is None or str(c).strip() == '' for c in row):
                    continue
                try:
                    if has_exam_col:
                        en = str(row[cand_idx['考试名称']] or '').strip()
                        if not en or en not in exam_name_map:
                            candidate_skipped += 1
                            continue
                        exam = exam_name_map[en]
                    else:
                        exam = default_exam

                    id_card = str(row[cand_idx['身份证号']] or '').strip()
                    name = str(row[cand_idx.get('姓名', -1)] or '').strip() if '姓名' in cand_idx else ''
                    if not id_card or not name:
                        candidate_skipped += 1
                        continue

                    candidate, cand_created = Candidate.objects.get_or_create(
                        id_card=id_card, defaults={'name': name},
                    )
                    if not cand_created and candidate.name != name:
                        candidate.name = name
                        candidate.save(update_fields=['name'])

                    _, ec_created = ExamCandidate.objects.get_or_create(
                        exam=exam, candidate=candidate,
                    )
                    if ec_created:
                        candidate_added += 1
                except Exception:
                    candidate_skipped += 1
                    continue

    # ── 返回统计结果 ──
    return {
        'success': True,
        'exam_created': exam_created,
        'exam_skipped': exam_skipped,
        'rule_created': rule_created,
        'rule_skipped': rule_skipped,
        'candidate_added': candidate_added,
        'candidate_skipped': candidate_skipped,
    }