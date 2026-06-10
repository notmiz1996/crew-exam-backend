# exam/utils/answer_mapping.py

"""
选项字母 → 选项文本的映射工具（§5.2）

核心函数：map_letter_to_text()
- 将考生选择的字母（如 "A"）映射为选项文本
- 用于与快照答案（original_answer）做文本比较

为什么需要映射？
  因为选项顺序被打乱了，每个考生的同一道题选项顺序不同。
  所以批改时不能比较字母（A/B/C...），必须比较字母对应的文本内容。

  例：
    原始选项： ["A. 北京", "B. 上海", "C. 广州", "D. 深圳"]
    正确答案快照（original_answer）= "A" → 映射为文本 "A. 北京"
    考生看到的 shuffled_options = ["C. 广州", "A. 北京", "D. 深圳", "B. 上海"]
    考生选了 "B"（实际是第二个选项 "A. 北京"）
      → 映射文本 = "A. 北京"
      → 比较：考生文本 "A. 北京" == 快照文本 "A. 北京" → 正确

两种输入格式：
  - 单选题/多选题：letter 为字母 "A"/"B"/"A,B,C"，走 ord() 索引
  - 判断题：letter 为全文本 "正确"/"错误"，直接查 options 列表
"""
from typing import Optional


def map_letter_to_text(options: list[str], letter: str) -> Optional[str]:
    """
    将选项字母 A/B/C... 映射为对应的选项文本

    参数：
        options: 选项列表，如 ["A. 北京", "B. 上海", ...] 或 ["正确", "错误"]
        letter: 单字母 "A"~"Z"（单选/判断），或全文本 "正确"/"错误"（判断题）

    返回：
        映射后的文本，如 "A. 北京"
        找不到时返回 None
    """
    if not options or not letter:
        return None

    # === 场景1：letter 为全文本（判断题 "正确"/"错误"，长度 >1）===
    if len(letter) > 1:
        # 直接看该文本是否在选项中
        if letter in options:
            return letter
        # 也不在选项中 → 无法映射
        return None

    # === 场景2：letter 为单字母（单选题 "A"/"B"，或判断题前端传的 "A"）===
    index = ord(letter.upper()) - ord('A')

    if index < 0 or index >= len(options):
        return None

    return options[index]


def map_multiple_letters_to_texts(options: list[str], letters: str) -> list[str]:
    """
    将多选题的逗号分隔字母串映射为文本列表

    参数：
        options: 选项列表
        letters: 如 "A,B,C"

    返回：
        文本列表，如 ["A. 选项A", "B. 选项B", "C. 选项C"]
        无效字母会被过滤掉
    """
    if not letters:
        return []

    parts = [p.strip() for p in letters.split(',')]
    texts = []

    for letter in parts:
        text = map_letter_to_text(options, letter)
        if text is not None:
            texts.append(text)

    return texts