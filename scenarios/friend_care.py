"""好友护理场景：单次遍历好友列表，遇到配置名单中的好友就护理。

流程（好友导航复用 visit.py：累积名单、按列表顺序切换）：
1. 点击 好友（visit_friends）-> 访问（visit）进入第一个好友宠物页
2. friend_name 支持中英文逗号分隔多个名称；名单只用于筛选，不要求配置顺序
3. 按护理好友方式（friend_care.method，选项同 care.method）逐个护理：
   - ocr检测：展开好友状态面板读体力/清洁，分别护理到配置目标值
   - 一键护理：好友页有一键护理按钮就点（含"支付并护理"确认），没有视为状态正常跳过
4. 整轮只打开一次好友页，沿列表走一遍；名单内好友处理完或列表结束后统一返回主页。

配置（config.yaml 的 friend_care 段）：enabled 开关 / time_range 时间段（HH:MM-HH:MM）/
friend_name 护理好友名称（多个用中英文逗号分隔）/ method 护理好友方式 /
max_scan_count 每轮最多遍历好友数 / interval_seconds 调度间隔（秒）。

运行：python scenarios/friend_care.py            （Ctrl+C 停止）
"""

import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.progress import log
from src.scenario import CLICK_INTERVAL, DeviceScenario
from scenarios.care import CARE_METHODS, ONE_CLICK_PAY_RETRIES, CareScenario
from scenarios.visit import VisitScenario

MAX_FRIEND_SWITCHES = 30  # 查找/切回目标好友时最多切换次数（防无限切换）
FRIEND_CARE_RETRIES = 2   # 当前好友护理偶发卡顿时的原地重试次数


def parse_friend_names(value: str) -> list[str]:
    """兼容旧的单好友字符串；多个名称用中英文逗号分隔并按输入顺序去重。"""
    return list(dict.fromkeys(name.strip() for name in re.split(r'[,，]', value)
                              if name.strip()))


def parse_time_range(value: str, name: str = 'friend_care.time_range') -> tuple:
    """解析时间段 'HH:MM-HH:MM' 为 (开始, 结束) time。"""
    try:
        start_s, end_s = str(value).split('-', 1)
        start = datetime.strptime(start_s.strip(), '%H:%M').time()
        end = datetime.strptime(end_s.strip(), '%H:%M').time()
    except ValueError:
        raise ValueError(
            f'config.yaml 中 {name} 格式无效: {value!r}，应为 HH:MM-HH:MM') from None
    return start, end


def in_time_range(now, start, end) -> bool:
    """now 是否在 [start, end) 时间段内（end <= start 视为跨零点，如 22:00-02:00）。"""
    if end > start:
        return start <= now < end
    return now >= start or now < end


class _FriendCare(CareScenario):
    """好友家护理：复用喂食/洗澡/状态面板流程，但不写自己的状态缓存
    （cache_care_items 会把好友的体力/库存写进当前账号缓存，污染 GUI 状态条）。"""

    _friend_page = True  # care._care_item 用于排除底部好友轮播的单项/末尾状态

    def cache_care_items(self, anchor: str, **status_fields) -> None:
        pass


class FriendCareScenario(VisitScenario):
    def __init__(self, dev=None):
        DeviceScenario.__init__(self, dev)  # 跳过 VisitScenario 的踩踩字段/日志
        fc = self.cfg.friend_care
        self.last_care_at: datetime | None = None  # 上次巡检完成时间（调度间隔用）
        log(f'好友护理: {"启用" if fc.enabled else "未启用"}，好友: {fc.friend_name or "未配置"}'
            f'，方式: {fc.method}，喂食目标: {fc.energy_target}，洗澡目标: {fc.clean_target}'
            f'，时间段: {fc.time_range}，调度间隔: {fc.interval_seconds}秒')

    # ---- 好友导航 ----

    def begin_friend_walk(self) -> None:
        """只打开一次好友页，并初始化按好友列表顺序遍历所需的状态。"""
        self._friends = []
        self._friend_index = 0
        self.goto_first_friend()

    def current_friend(self) -> tuple[str, list[tuple[str, int, int]]]:
        """返回当前好友描述和当前可见列表，并把新出现的好友并入累积名单。"""
        visible = self._wait_friend_items(required=True)
        for desc, _, _ in visible:
            if desc and desc not in self._friends:
                self._friends.append(desc)
        if self._friend_index >= len(self._friends):
            raise RuntimeError('无法确定当前好友')
        return self._friends[self._friend_index], visible

    def switch_to_friend(self, name: str, max_switches: int = MAX_FRIEND_SWITCHES) -> bool:
        """在好友列表里找到名称含 name 的好友并点击切换，返回是否成功。

        列表滚动加载（控件树里只有当前可见项）：可见项没有目标时按 visit 的
        累积名单逻辑切下一个好友加载更多，直到找到或没有更多好友。
        """
        max_switches = self.wait_attempts(max_switches)
        for _ in range(max_switches):
            visible = self._friend_items()
            if not visible:
                # 点访问后 visit 消失不代表好友家已渲染完（模拟器上加载慢），
                # 列表还是空的就等一轮再抓，避免误判"好友不存在"
                log('好友列表还没加载出来，等待重试')
                time.sleep(CLICK_INTERVAL)
                continue
            new = [desc for desc, _, _ in visible if desc and desc not in self._friends]
            for desc in new:
                self._friends.append(desc)
            for desc, x, y in visible:
                if name in desc:
                    log(f'切换到好友 {desc} ({x}, {y})')
                    self.click(x, y)
                    time.sleep(CLICK_INTERVAL)
                    self._friend_index = self._friends.index(desc)
                    return True
            if not self.next_friend(visible):
                return False
        log(f'切换 {max_switches} 次仍未找到好友 {name}')
        return False

    def goto_friend_home(self, name: str) -> None:
        """好友面板 -> 访问 -> 依次切换好友列表，直到进入名称为 name 的好友家。"""
        self._friends = []        # 累积好友名单（只增不减），见 visit.py
        self._friend_index = 0    # 访问进入时默认第一个好友
        self.goto_first_friend()
        if not self.switch_to_friend(name):
            raise RuntimeError(f'好友列表中未找到好友: {name}')

    # ---- 护理 ----

    def care_friend(self, times: int = 0) -> bool:
        """按护理好友方式护理当前好友家的宠物一次，返回是否执行了护理动作。

        times: 冗余字段"护理次数"（预留给后续按次数限制/计数改造，当前不使用）。
        ocr检测：展开好友状态面板读体力/清洁，不足则分别护理到配置目标；
        一键护理：好友页有一键护理按钮就点，没有视为状态正常跳过。
        """
        if self.method == '一键护理':
            hit = self.see('one_click_care')
            if not hit:
                log('未找到一键护理按钮（好友体力/清洁正常），跳过护理')
                return False
            log('好友护理：使用一键护理')
            self.click(hit[0], hit[1])
            # 支付确认弹窗可能比护理按钮点击晚一拍出现，短等几次再判断（同 care.py）
            for attempt in range(1, ONE_CLICK_PAY_RETRIES + 1):
                pay = self.see('one_click_pay')
                if pay:
                    log('检测到"支付并护理"，点击确认')
                    self.click(pay[0], pay[1])
                    time.sleep(CLICK_INTERVAL)
                    break
                if attempt < ONE_CLICK_PAY_RETRIES:
                    time.sleep(CLICK_INTERVAL)
            return True
        care = _FriendCare(self.dev)
        care.energy_threshold = self.energy_target
        care.clean_threshold = self.clean_target
        care.toggle_status()
        status = care.read_status_ready()
        source = self.dev.hierarchy()
        energy = status.get('体力')
        clean = status.get('清洁')
        log(f'好友状态: 体力={energy}（目标 {self.energy_target}） '
            f'清洁={clean}（目标 {self.clean_target}）')
        cared = False
        if energy is not None and energy < self.energy_target:
            log(f'好友体力 {energy} < {self.energy_target}，喂食')
            care.feed(source)
            cared = True
            source = self.dev.hierarchy()
        if clean is not None and clean < self.clean_target:
            log(f'好友清洁 {clean} < {self.clean_target}，洗澡')
            care.shower(source)
            cared = True
            source = self.dev.hierarchy()
        if cared:
            source = care.exit_care_mode(source)
        if care.close_status(source):
            log('好友状态检查完成，已收起宠物状态')
        else:
            log('好友状态检查完成，状态栏未展开')
        return cared

    # ---- 入口 ----

    def run(self, max_times: int | None = None, max_rounds: int = 0) -> bool:
        """好友页只进入一次，按列表顺序遍历，遇到配置名单中的好友就护理。

        每次调度只做一次护理巡检（调度间隔 friend_care.interval_seconds 由
        执行器的 friend_care_due() 控制），场景内不再等待/切换好友刷新状态。
        max_times / max_rounds 参数仅为与其他场景签名一致（预留）。
        返回 True 表示完成了一次巡检（无论是否执行护理动作）——返回 False 会被
        任务队列标记当天不可继续，"好友无需护理"也必须返回 True 以便间隔后复查。
        """
        fc = self.cfg.friend_care
        if not fc.enabled:
            log('好友护理未启用，跳过')
            return False
        names = parse_friend_names(fc.friend_name)
        if not names:
            log('未配置护理好友名称，跳过好友护理')
            return False
        self.method = fc.method
        if self.method not in CARE_METHODS:
            raise ValueError(
                f'config.yaml 中 friend_care.method 配置无效: {self.method!r}，'
                f'可选: {"/".join(CARE_METHODS)}')
        self.energy_target = int(fc.energy_target)
        self.clean_target = int(fc.clean_target)
        scan_limit = int(getattr(fc, 'max_scan_count', 20))
        if not 0 <= self.energy_target <= 100 or not 0 <= self.clean_target <= 100:
            raise ValueError('friend_care.energy_target / clean_target 必须在 0-100 之间')
        if scan_limit < 1:
            raise ValueError('friend_care.max_scan_count 必须大于 0')
        start, end = parse_time_range(fc.time_range)
        if not in_time_range(datetime.now().time(), start, end):
            log(f'当前不在好友护理时间段 {fc.time_range} 内，跳过')
            return False
        log(f'好友护理开始: 好友={", ".join(names)}，方式={self.method}，'
            f'喂食目标={self.energy_target}，洗澡目标={self.clean_target}，'
            f'时间段={fc.time_range}；按好友列表顺序单次遍历，最多 {scan_limit} 位')
        cared_any = False
        checked = 0
        failures = []
        handled: set[str] = set()
        scanned = 0
        attempts = self.wait_attempts(FRIEND_CARE_RETRIES)
        self.ensure_main_page()
        self.begin_friend_walk()
        try:
            while True:
                desc, visible = self.current_friend()
                scanned += 1
                matched = next((name for name in names
                                if name not in handled and name in desc), None)
                if matched is not None:
                    handled.add(matched)
                    cared = False
                    last_error = None
                    log(f'列表遇到护理目标: {desc}（配置名 {matched}）')
                    for attempt in range(1, attempts + 1):
                        try:
                            cared = self.care_friend()
                            checked += 1
                            cared_any = cared_any or cared
                            log(f'好友 {matched} 巡检完成'
                                + ('，本次执行了护理' if cared else '，本次无需护理'))
                            break
                        except Exception as e:
                            last_error = e
                            log(f'好友 {matched} 第 {attempt}/{attempts} 次护理尝试失败: {e}')
                            if attempt < attempts:
                                time.sleep(CLICK_INTERVAL)
                    else:
                        failures.append((matched, last_error))
                        log(f'好友 {matched} 多次尝试仍失败，继续遍历下一位')
                if len(handled) >= len(names):
                    break
                if scanned >= scan_limit:
                    log(f'好友护理已遍历 {scanned} 位，达到设置上限，结束本轮查找')
                    break
                if not self.next_friend(visible):
                    break
        finally:
            self.close()
            self.ensure_main_page()
        missing = [name for name in names if name not in handled]
        if missing:
            log('本轮好友列表中未遇到: ' + '、'.join(missing))
        if checked == 0 and failures:
            details = '；'.join(f'{name}: {error}' for name, error in failures)
            raise RuntimeError(f'所有护理好友均巡检失败：{details}')
        if checked == 0 and not handled:
            log('本轮遍历范围内未找到已配置的护理好友，按“找到几个算几个”正常结束')
        if failures:
            log('好友护理部分失败: ' + '、'.join(name for name, _ in failures))
        log(f'好友护理巡检完成: 遍历 {scanned}/{scan_limit} 位，成功 {checked}/{len(names)} 位'
            + ('，本轮执行过护理' if cared_any else '，本轮均无需护理'))
        self.last_care_at = datetime.now()
        return True


if __name__ == '__main__':
    try:
        FriendCareScenario().run()
    except KeyboardInterrupt:
        log('手动停止')
