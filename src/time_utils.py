"""调度时间的输入归一化与区间判断。"""
from datetime import time
import re
import unicodedata


def parse_clock(value, default_second: int = 0) -> time:
    if isinstance(value, int) and not isinstance(value, bool):
        # 兼容 YAML 1.1 把未加引号的 HH:mm 加载成分钟数。
        return time(value // 60, value % 60, default_second)
    text = unicodedata.normalize('NFKC', str(value)).strip()
    if re.fullmatch(r'\d{4}', text):
        text = text[:2] + ':' + text[2:]
    if not re.fullmatch(r'\d{1,2}:\d{1,2}(?::\d{1,2})?', text):
        raise ValueError('时间应为 HH:mm，如 08:30 或 0830')
    parts = [int(part) for part in text.split(':')]
    if len(parts) == 2:
        parts.append(default_second)
    return time(*parts)


def parse_range(value, *, legacy_equal: bool = False) -> tuple[time, time]:
    text = unicodedata.normalize('NFKC', str(value)).strip()
    text = re.sub(r'[–—~～至]', '-', text)
    if re.fullmatch(r'\d{8}', text):
        text = text[:4] + '-' + text[4:]
    parts = text.split('-')
    if len(parts) != 2:
        raise ValueError('时间段应为 HH:mm-HH:mm，如 08:30-19:45')
    start, end = parse_clock(parts[0], 0), parse_clock(parts[1], 59)
    # 旧配置用相同的分钟级起止表示全天，新输入保存明确的秒数后按新规则执行。
    if (legacy_equal and all(part.count(':') <= 1 for part in parts)
            and start.hour == end.hour and start.minute == end.minute):
        end = start
    return start, end


def clock_text(value) -> str:
    return parse_clock(value).strftime('%H:%M')


def range_text(value, *, legacy_equal: bool = False) -> str:
    start, end = parse_range(value, legacy_equal=legacy_equal)
    return f'{start:%H:%M:%S}-{end:%H:%M:%S}'


def display_range(value) -> str:
    start, end = parse_range(value)
    return f'{start:%H:%M}-{end:%H:%M}'


def in_clock_range(now: time, start: time, end: time) -> bool:
    now = now.replace(microsecond=0)
    if end > start:
        return start <= now <= end
    return now >= start or now <= end
