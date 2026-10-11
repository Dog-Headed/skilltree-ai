import re


# 点号后的空格区分 A. 选项 与 hello.py 这样的文件名。
OPTION_PREFIX = re.compile(
    r"^\s*([A-Z]{1,2})(?:[.．]\s+|[、):：]\s*)(.+)$", re.IGNORECASE | re.DOTALL
)


def option_label(index: int) -> str:
    label = ""
    index += 1
    while index:
        index, digit = divmod(index - 1, 26)
        label = chr(ord("A") + digit) + label
    return label


def display_option(index: int, option: str) -> str:
    if OPTION_PREFIX.match(option):
        return option
    return f"{option_label(index)}. {option}"


def normalize_choice_answer(answer, options: list[str]):
    """将选项字母或完整选项内容统一成试卷中保存的选项。"""
    if not isinstance(answer, str):
        return answer
    value = answer.strip()
    prefixes = [OPTION_PREFIX.match(option) for option in options]

    # 完整文本优先，避免把原本就是字母的选项内容当成位置。
    for option, prefix in zip(options, prefixes):
        if value == option.strip() or (prefix and value == prefix.group(2).strip()):
            return option

    # 已有 A. / B. 标号时遵循原标号，未标号的选项使用位置标号。
    for index, (option, prefix) in enumerate(zip(options, prefixes)):
        label = prefix.group(1).upper() if prefix else option_label(index)
        if value.upper() == label:
            return option

    return value
