"""每日次数/时长进度持久化（对外兼容入口，底层统一由 src/progress_store.py 管理）。

进度文件固定为 runs/ 下的单文件（学习/打工/冒险/踩踩/PK/被雇佣/雇佣好友/
经验日常各一个）。跨天规整、原子写入、损坏兜底都在 src/progress_store.py，
这里只保留文件常量、日志与各场景/runner/GUI 依赖的函数签名，保证调用方不变。
测试重定向进度文件仍按老习惯 monkeypatch 本模块的文件常量即可（函数在调用时
才读模块全局常量，会拿到新值）。
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from .config import PROJECT_ROOT

SCHOOL_PROGRESS_FILE = PROJECT_ROOT / 'runs' / 'school_progress.json'
WORK_PROGRESS_FILE = PROJECT_ROOT / 'runs' / 'work_progress.json'
ADVENTURE_PROGRESS_FILE = PROJECT_ROOT / 'runs' / 'adventure_progress.json'
ADVENTURE_RECALL_PROGRESS_FILE = PROJECT_ROOT / 'runs' / 'adventure_recall_progress.json'
EMPLOYED_PROGRESS_FILE = PROJECT_ROOT / 'runs' / 'employed_progress.json'
VISIT_PROGRESS_FILE = PROJECT_ROOT / 'runs' / 'visit_progress.json'
PK_PROGRESS_FILE = PROJECT_ROOT / 'runs' / 'pk_progress.json'
HIRE_FRIEND_PROGRESS_FILE = PROJECT_ROOT / 'runs' / 'hire_friend_progress.json'
HIRE_FRIEND_FAILURE_PROGRESS_FILE = PROJECT_ROOT / 'runs' / 'hire_friend_failure_progress.json'
EXP_DAILY_PROGRESS_FILE = PROJECT_ROOT / 'runs' / 'exp_daily_progress.json'


def log(msg: str) -> None:
    line = f'[{time.strftime("%H:%M:%S")}] {msg}'
    try:  # 打包成 --windowed 后没有控制台，stdout 可能是无效流，不能让它拖垮日志
        print(line, flush=True)
    except (OSError, UnicodeError):
        pass
    try:  # 写入日志文件 runs/logs/YYYY-MM-DD.log
        log_dir = PROJECT_ROOT / 'runs' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / f'{date.today().isoformat()}.log', 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass
    for listener in _log_listeners:
        try:
            listener(line)
        except Exception:
            pass


_log_listeners: list = []


def add_log_listener(fn) -> None:
    """注册日志监听器（GUI 实时日志用），每行日志都会回调 fn(line)。"""
    _log_listeners.append(fn)


from . import progress_store  # noqa: E402  (需要先定义 log 再注册给 store)

progress_store.set_logger(log)


def load_progress(progress_file: Path, quiet: bool = False) -> tuple[str, int, dict]:
    """读取持久化进度，返回 (今天日期, 当天已完成次数, 历史记录 {日期: 次数})。

    跨天时把旧日期的次数归档进 history（内存归档，不落盘）。quiet=True 时不打印续跑日志。
    """
    today, done, history = progress_store.load_daily(progress_file)
    if done and not quiet:
        log(f'读取到今天已完成 {done} 次，继续计数')
    return today, done, history


def save_progress(progress_file: Path, today: str, done: int, history: dict) -> None:
    """持久化当天次数和历史记录 {日期: 次数}。

    底层 save_daily 会先做跨天规整：旧日期的累计时长（study_secs/work_secs）等
    会被清掉，根治"昨天的工作时长漏进今天"；写入走原子替换。
    """
    progress_store.save_daily(progress_file, today, done, history)


def log_history(history: dict, today: str) -> None:
    """启动时打印历史记录（不含今天）。"""
    past = {d: c for d, c in sorted(history.items()) if d != today and c}
    if past:
        log('历史记录: ' + '，'.join(f'{d} {c} 次' for d, c in past.items()))


def increment_progress(progress_file: Path) -> int:
    """给指定进度文件的当天次数 +1 并保存，返回新次数。"""
    return progress_store.increment_daily(progress_file)


# ---- 经验日常（踩踩时顺带做：好友页照顾区域有 exp 就点一键护理） ----


def load_exp_daily(quiet: bool = False) -> tuple[str, bool, dict]:
    """读取经验日常进度，返回 (今天日期, 当日是否完成, 历史记录 {日期: 是否完成})。"""
    today, done, history = progress_store.load_exp_daily(EXP_DAILY_PROGRESS_FILE)
    if not quiet:
        log(f'经验日常: ' + ('已完成' if done else '未完成'))
    return today, done, history


def save_exp_daily(done: bool, today: str | None = None, history: dict | None = None) -> None:
    """持久化当天经验日常是否完成和历史记录。"""
    progress_store.save_exp_daily(EXP_DAILY_PROGRESS_FILE, done, today, history)


def exp_daily_done() -> bool:
    """今天经验日常是否已完成（供调度判断是否仍需处理）。"""
    _, done, _ = load_exp_daily(quiet=True)
    return done


def log_exp_daily() -> None:
    """打印经验日常当天状态与历史（日志/GUI 显示用）。"""
    today, done, history = load_exp_daily(quiet=True)
    past = {d: v for d, v in sorted(history.items()) if d != today}
    line = f'经验日常: ' + ('已完成' if done else '未完成')
    if past:
        line += '（历史: ' + '，'.join(f'{d} ' + ('完成' if v else '未完成')
                                      for d, v in past.items()) + '）'
    log(line)


# 活动类型 -> (进度文件, 中文量词, 计数名)，用于出门时等完别的活动后的交叉计数
CROSS_PROGRESS = {
    'school': (SCHOOL_PROGRESS_FILE, '一节课', '学习'),
    'work': (WORK_PROGRESS_FILE, '一次打工', '打工'),
    'adventure': (ADVENTURE_PROGRESS_FILE, '一次冒险', '冒险'),
    'employed': (EMPLOYED_PROGRESS_FILE, '一次被雇佣', '被雇佣'),
}


def count_cross(finished: str) -> None:
    """出门时等完了别的活动，计入对应进度并打日志；学习/打工顺带累计时长。"""
    file, unit, name = CROSS_PROGRESS[finished]
    n = increment_progress(file)
    log(f'出门时等完了{unit}，已计入{name}次数（{n} 次）')
    if finished == 'school':
        record_study_finish()
    elif finished == 'work':
        record_work_finish()


# ---- 学习/工作时长累计（学习按自动识别/配置兜底、打工按选择时长结算） ----
# 各学园一节课对应的学习时长（秒）
SCHOOL_DURATION_SECONDS = {
    '初级学园': 10 * 60,
    '中级学园': 20 * 60,
    # 未持久化手动时长的旧进度回退值；当前实测为 135 分钟。
    '高级学园': 135 * 60,
    '进修学院': 45 * 60,
}
# 打工时长配置 -> 单次打工时长（秒）
WORK_DURATION_SECONDS = {
    '10分钟': 10 * 60,
    '45分钟': 45 * 60,
    '2小时': 2 * 3600,
}


def get_current_school() -> str | None:
    """school_progress.json 里持久化的当前学园（学习开始时写入，跨天视为空）。"""
    return progress_store.get_daily_field(SCHOOL_PROGRESS_FILE, 'school')


def set_current_school(school: str, duration_minutes: int | None = None) -> None:
    """学习开始时原子记录当前学园及本节识别值或配置兜底时长。"""
    values = {'school': school}
    if duration_minutes is not None and int(duration_minutes) > 0:
        values['duration_minutes'] = int(duration_minutes)
    progress_store.set_daily_fields(SCHOOL_PROGRESS_FILE, values)


def get_current_study_minutes() -> int | None:
    """本节持久化的学习分钟数；旧进度按学园默认值兜底。"""
    saved = progress_store.to_int(
        progress_store.get_daily_field(SCHOOL_PROGRESS_FILE, 'duration_minutes'))
    if saved > 0:
        return saved
    school = get_current_school()
    seconds = SCHOOL_DURATION_SECONDS.get(school or '')
    return seconds // 60 if seconds else None


def get_current_work_duration() -> str | None:
    """work_progress.json 里持久化的本次打工时长（work.duration）。"""
    return progress_store.get_daily_field(WORK_PROGRESS_FILE, 'duration')


def set_current_work_duration(duration: str) -> None:
    """打工开始时记录本次打工时长（work.duration）：跨天总是落盘，否则值变化才写。"""
    progress_store.set_daily_field(WORK_PROGRESS_FILE, 'duration', duration)


def _today_seconds(progress_file: Path, key: str) -> int:
    return progress_store.today_seconds(progress_file, key)


def _add_seconds(progress_file: Path, key: str, seconds: int) -> int:
    return progress_store.add_seconds(progress_file, key, seconds)


def record_study_finish() -> int | None:
    """一节课结算：按学习开始后持久化的识别值或配置兜底时长累计。"""
    school = get_current_school()
    minutes = get_current_study_minutes()
    if not minutes:
        return None
    secs = minutes * 60
    total = _add_seconds(SCHOOL_PROGRESS_FILE, 'study_secs', secs)
    log(f'学习结算: {school} +{secs // 60} 分钟，今日已学习 {total // 60} 分钟')
    return total


def record_work_finish() -> int | None:
    """一次打工结算：按持久化的打工时长累计打工时长（秒）。"""
    duration = get_current_work_duration()
    secs = WORK_DURATION_SECONDS.get(duration or '')
    if not secs:
        return None
    total = _add_seconds(WORK_PROGRESS_FILE, 'work_secs', secs)
    log(f'打工结算: 时长 {duration} +{secs // 60} 分钟，今日已打工 {total // 60} 分钟')
    return total


def _migrate_old_durations(progress_file: Path, key: str, minutes_per: int) -> None:
    """老版本进度今天只有次数（learned）、没有时长字段时，按
    次数 x minutes_per 分钟 换算时长并落盘（只迁移一次，之后 study_secs 存在即跳过）。"""
    if minutes_per <= 0:
        return
    data = progress_store.read_raw(progress_file)
    if data.get('date') != date.today().isoformat():
        return
    if key in data:
        return  # 已有新字段（含 0），跳过
    count = progress_store.to_int(data.get('learned', 0))
    if count <= 0:
        return
    data[key] = count * minutes_per * 60
    progress_store.write_raw(progress_file, data)
    log(f'迁移老进度: {progress_file.stem} 今天 {count} 次 x {minutes_per} 分钟'
        f' = {count * minutes_per} 分钟')


def _ensure_work_duration_floor() -> None:
    """修补打工次数已计入、时长却因旧版本/异常收尾漏记的当天数据。

    每次打工最短也有 10 分钟，因此只在 ``打工次数 x 10 分钟`` 大于当前
    ``work_secs`` 时抬高到这个保守下限；已经按 45 分钟/2 小时正确累计的时长
    不会被覆盖。该修补幂等，只会在确有缺口时写盘并记录一次日志。
    """
    data = progress_store.read_raw(WORK_PROGRESS_FILE)
    if data.get('date') != date.today().isoformat():
        return
    count = progress_store.to_int(data.get('learned', 0))
    current = progress_store.to_int(data.get('work_secs', 0))
    minimum = count * WORK_DURATION_SECONDS['10分钟']
    if minimum <= current:
        return
    data['work_secs'] = minimum
    progress_store.write_raw(WORK_PROGRESS_FILE, data)
    log(f'修补打工时长: 今天 {count} 次至少 {minimum // 60} 分钟'
        f'（原统计 {current // 60} 分钟）')


def _initialize_study_duration(duration_minutes: int) -> None:
    """为旧进度补上手动时长，并修正高级学园曾使用的 30/150 分钟旧值。

    只处理尚无 ``duration_minutes`` 的旧进度；写入后不再反复改动，因此用户以后
    调整时长只影响后续课程，不会重算已经结算的课程。
    """
    if duration_minutes <= 0:
        return
    data = progress_store.read_raw(SCHOOL_PROGRESS_FILE)
    if (data.get('date') != date.today().isoformat() or not data.get('school')
            or progress_store.to_int(data.get('duration_minutes')) > 0):
        return
    count = progress_store.to_int(data.get('learned', 0))
    current = progress_store.to_int(data.get('study_secs', 0))
    if (data.get('school') == '高级学园' and count > 0
            and current in (count * 30 * 60, count * 150 * 60)):
        corrected = count * duration_minutes * 60
        data['study_secs'] = corrected
        log(f'修正高级学园学习时长: 今天 {count} 次由 {current // 60} 分钟改为'
            f' {corrected // 60} 分钟')
    data['duration_minutes'] = duration_minutes
    progress_store.write_raw(SCHOOL_PROGRESS_FILE, data)


def load_durations(school_factor: int = 0, work_factor: int = 0,
                   study_duration_minutes: int = 135) -> tuple[int, int]:
    """今天已累计 (学习秒, 打工秒)。

    首次运行新版本：老进度今天只有次数没有时长时，按旧版 学习/打工点数系数
    （即每节/每次的分钟数）自动换算补上，之后正常累计。
    """
    # 学习时长由自动识别或用户配置兜底；旧 school_factor 只保留函数签名兼容。
    _migrate_old_durations(SCHOOL_PROGRESS_FILE, 'study_secs', study_duration_minutes)
    _migrate_old_durations(WORK_PROGRESS_FILE, 'work_secs', work_factor)
    _initialize_study_duration(study_duration_minutes)
    _ensure_work_duration_floor()
    return (_today_seconds(SCHOOL_PROGRESS_FILE, 'study_secs'),
            _today_seconds(WORK_PROGRESS_FILE, 'work_secs'))
