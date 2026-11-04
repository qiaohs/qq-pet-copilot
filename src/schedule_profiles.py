"""本地命名调度方案。只保存调度字段，不复制连接、名单或推送凭据。"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from .config import APP_ROOT, TASK_KEYS, TasksConfig, load_config
from . import settings

PROFILE_FILE = APP_ROOT / 'runs' / 'schedule_profiles.json'
BACKUP_NAME = '切换前（自动备份）'
SCENE_FIELDS = {
    'care': ('interval_seconds',),
    'friend_care': ('enabled', 'interval_seconds', 'time_range'),
    'hire_friend': ('enabled', 'interval_seconds', 'time_range', 'times_per_day'),
    'employed': ('enabled', 'interval_seconds', 'off_hours_interval_seconds', 'time_range'),
    'school': ('times_per_day', 'duration_minutes', 'duration_candidates'),
    'work': ('times_per_day', 'location', 'duration'),
    'adventure': ('times_per_day', 'start_time', 'type', 'batch'),
    'visit': ('start_time', 'continuous_target', 'exit_complete_count'),
    'pk': ('start_time', 'times_per_day'),
    'schedule': ('coin_threshold', 'daily_hour_limit'),
}
ALLOWED_KEYS = {
    *(f'tasks.{key}' for key in ('order', 'main_order', 'failure_interval')),
    *(f'tasks.{task}.{key}' for task in TASK_KEYS
      for key in asdict(getattr(TasksConfig(), task))),
    *(f'{scene}.{key}' for scene, fields in SCENE_FIELDS.items() for key in fields),
}


def capture(config=None) -> dict:
    cfg = config or load_config()
    result = {f'tasks.{key}': copy.deepcopy(getattr(cfg.tasks, key))
              for key in ('order', 'main_order', 'failure_interval')}
    for task in TASK_KEYS:
        result.update({f'tasks.{task}.{key}': value
                       for key, value in asdict(getattr(cfg.tasks, task)).items()})
    for scene, fields in SCENE_FIELDS.items():
        result.update({f'{scene}.{key}': copy.deepcopy(getattr(getattr(cfg, scene), key))
                       for key in fields})
    # YAML 1.1 的未加引号 HH:MM 会加载为分钟数，与现有调度器保持兼容。
    def clock_text(value):
        return f'{value // 60:02d}:{value % 60:02d}' if isinstance(value, int) else value
    for key, value in list(result.items()):
        if key.endswith('.daily_times'):
            result[key] = [clock_text(t) for t in value or []]
        elif key.endswith('.start_time'):
            result[key] = clock_text(value)
    return result


def validate(values: dict) -> dict:
    if not isinstance(values, dict) or not values or set(values) - ALLOWED_KEYS:
        raise ValueError('方案包含无效或非调度字段，请重新保存方案')
    result = {}
    for key, value in values.items():
        if key.startswith('tasks.') and key.count('.') == 2:
            field = key.rsplit('.', 1)[1]
            if field == 'enabled':
                ok = isinstance(value, bool)
            elif field == 'trigger':
                ok = value in ('interval', 'daily')
            elif field == 'daily_times':
                ok = isinstance(value, list) and all(
                    settings.validate_field('adventure.start_time', t)[0] for t in value)
            elif field == 'enabled_time_range':
                try:
                    from datetime import datetime
                    parts = str(value).split('-')
                    ok = len(parts) == 2
                    for part in parts:
                        datetime.strptime(part.strip(), '%H:%M:%S' if part.count(':') == 2 else '%H:%M')
                except ValueError:
                    ok = False
            else:
                ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else:
            ok, value = settings.validate_field(key, value)
        if not ok:
            raise ValueError(f'方案中的 {key} 值无效')
        result[key] = copy.deepcopy(value)
    return result


def differences(current: dict, target: dict) -> list[tuple]:
    target = validate(target)
    return [(key, current.get(key), value) for key, value in target.items()
            if current.get(key) != value]


def load_store(path: Path | None = None) -> dict:
    path = path or PROFILE_FILE
    if not path.exists():
        return {'version': 1, 'profiles': {}}
    with path.open(encoding='utf-8') as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get('profiles'), dict):
        raise ValueError('调度方案文件格式无效，原文件已保留')
    return data


def save_store(data: dict, path: Path | None = None) -> None:
    path = path or PROFILE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def apply(values: dict, expected_current: dict) -> None:
    """用户确认差异后重新读取配置，只替换白名单字段；保留期间人工修改。"""
    values = validate(values)
    current = capture()
    if current != expected_current:
        raise ValueError('调度设置在预览期间发生了变化，请重新预览后应用')
    data = settings.load_raw()
    for key, _, value in differences(current, values):
        settings.set_value(data, key, value)
    settings.save_raw(data)
