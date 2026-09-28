"""踩踩场景：访问好友宠物页点"踩踩"。

流程（u2 控件定位，分辨率无关）：
1. 点击 好友（visit_friends）打开好友面板
2. 点击 访问（visit）进入第一个好友的宠物页
   （模拟器模式：门禁已翻转（scheme 路径）时与真机一致；门禁未翻转
   （frida 兜底）时改为 root am start 直开好友页，见 goto_first_friend）
3. 点击 踩踩（visit_step），当天次数 +1 并持久化到 runs/visit_progress.json
   （访问进入时默认就是好友列表的第一个好友）；
   若出现已踩标志（visit_stepped，"已踩"——今天已踩过该好友），
   跳过不计数，直接切换下一个好友
4. 切换下一个好友：重新抓取好友列表（content-desc 以 "好友 " 开头的项，
   注意空格，和入口按钮"好友"区分），按列表顺序点下一个。
   列表是滚动加载的，控件树里只有当前可见项，所以内部维护一份
   累积好友名单：每次抓取只把新出现的好友追加到尾部、不删除滚出
   屏幕的项，切换索引基于累积名单才不会乱；
   一旦进入就尽量连续运行，直到达到 continuous_target（默认 950）或没有更多好友
5. 结束：关闭好友页面（点 back 直到 visit/visit_step 都消失）
6. 若场景因异常、程序重启等已经退出，下次调度时进度达到
   exit_complete_count（默认 200）就把今日踩踩视为完成，不再从第一个好友重放

运行方式：
- run()：独立运行，开头/结尾 ensure_main_page（执行器在主页面调度用）

运行：python scenarios/visit.py            （Ctrl+C 停止）
      python scenarios/visit.py --times 5 （覆盖本次连续目标，0 为不限）
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import opener
from src.locators import LOCATORS, see_bounds
from src.ocr import ocr_texts
from src.progress import (
    VISIT_PROGRESS_FILE,
    load_exp_daily,
    load_progress,
    log,
    log_exp_daily,
    log_history,
    save_exp_daily,
    save_progress,
)
from src.scenario import CLICK_INTERVAL, NAV_TIMEOUT, DeviceScenario
from scenarios.care import ONE_CLICK_PAY_RETRIES

FRIEND_ITEM_XPATH = LOCATORS['visit_friend_item']['xpath'][0]
STEP_RETRIES = 5  # 切换好友后踩踩按钮有几秒加载延迟，重试次数
FRIEND_LIST_RETRIES = 5  # 好友页左侧列表可能晚于踩踩按钮出现
FRIEND_SWITCH_CLICK_RETRIES = 2  # 好友轮播点击偶尔未生效，验证失败后重点一次
FRIEND_SWITCH_POLL_RETRIES = 2  # 每次点击后等待轮播位置/名单实际变化

PROGRESS_FILE = VISIT_PROGRESS_FILE


def visit_finished_after_exit(done: int, continuous_target: int,
                              exit_complete_count: int) -> bool:
    """场景已经退出后，当前进度是否足以结束今日踩踩。

    continuous_target 是本轮没中断时的完整目标；exit_complete_count 只在下一次
    调度/重新进入前使用，0 表示禁用提前完成。当前运行中的循环不会调用本函数，
    因而经过 200 时仍会继续踩到 950。
    """
    return ((continuous_target > 0 and done >= continuous_target)
            or (exit_complete_count > 0 and done >= exit_complete_count))


class VisitScenario(DeviceScenario):
    def __init__(self, dev=None):
        super().__init__(dev)
        self.continuous_target = int(self.cfg.visit.continuous_target)
        self.exit_complete_count = int(self.cfg.visit.exit_complete_count)
        if self.continuous_target < 0 or self.exit_complete_count < 0:
            raise ValueError('visit.continuous_target / exit_complete_count 不能为负数')
        self._exp_handled = False  # 本轮是否处理过经验照顾（点击/判定完成）
        log(f'踩踩连续目标: {self.continuous_target if self.continuous_target else "不踩"}，'
            f'退出后完成阈值: '
            f'{self.exit_complete_count if self.exit_complete_count else "禁用"}')
        legacy_target = getattr(self.cfg.visit, 'times_per_day', None)
        if legacy_target is not None:
            log(f'旧配置 visit.times_per_day={legacy_target} 仅保留兼容，不再参与调度；'
                '请在任务页使用“踩踩连续运行目标”')

    # ---- 各阶段 ----

    def goto_first_friend(self) -> None:
        """好友面板 -> 访问 -> 第一个好友宠物页（出现踩踩按钮）。

        模拟器模式（opener.EMULATOR_MODE）：门禁已本地翻转（opener.GATE_OPEN，
        scheme 路径）时游戏内"访问"与真机一致直接可用；仅当走了 frida 兜底
        （门禁仍关）才用 root am start 直开好友宠物页
        （petUin=好友入口缓存的 uin + attrs，见 src/opener.py）。
        """
        if opener.EMULATOR_MODE and not opener.GATE_OPEN:
            self._goto_first_friend_emulator()
            return
        self.click_until_gone_or_see('visit_friends', 'visit', '打开好友列表')
        # 这里还是“好友”竖向名单（昵称 + 访问按钮），尚未进入好友宠物页；
        # visit_friend_item 定位的是进入后底部的“好友 xxx”横向轮播，在此必然为空。
        # 不做无效的 5 轮预等待，直接点“访问”，进入后再读取底部好友栏。
        # 不额外等固定 1 秒：点访问靠 click_until_gone_or_see 重试（点不中下一轮再点）
        self.click_until_gone_or_see('visit', 'visit_step', '访问好友')

    def _goto_first_friend_emulator(self) -> None:
        """模拟器 frida 兜底（门禁未翻转）：am start 直开好友宠物页；
        缓存失效则重新捕获一次再试。"""
        adb = self.dev.adb.adb
        serial = self.dev.adb.serial
        for attempt in (1, 2):
            entry = opener.ensure_friend_entry(adb, serial, self.dev)
            opener.am_start_pet_page(adb, serial, entry['uin'], entry['attrs'])
            # 等好友页渲染（踩踩/已踩 按钮出现）。好友页 chrome（按钮/好友列表）
            # 首次加载偏慢（实测可能 >10 秒），等待轮数给足 NAV_TIMEOUT*2
            for _ in range(self.wait_attempts(NAV_TIMEOUT * 2)):
                source = self.dev.hierarchy()
                if (self.see('visit_step', source=source)
                        or self.see('visit_stepped', source=source)):
                    return
                time.sleep(CLICK_INTERVAL)
            opener.invalidate_friend_entry()
            log(f'am start 进好友页超时，好友入口缓存可能失效，重新捕获 ({attempt}/2)')
        raise RuntimeError('好友页未找到踩踩按钮（am start 直开 + 重新捕获均失败）')

    def step_once(self) -> str:
        """点一次踩踩，返回 'stepped'；检测到已踩标志（今天踩过该好友）
        返回 'already' 由调用方跳过切换下一个（切换好友后按钮有加载延迟，重试几次）。"""
        attempts = self.wait_attempts(STEP_RETRIES)
        for attempt in range(1, attempts + 1):
            source = self.dev.hierarchy()
            if self.see('visit_stepped', source=source):
                return 'already'
            hit = self.see('visit_step', source=source)
            if hit:
                self.click(hit[0], hit[1])
                time.sleep(CLICK_INTERVAL)
                return 'stepped'
            log(f'未找到踩踩按钮，等待重试 ({attempt}/{attempts})')
            time.sleep(CLICK_INTERVAL)
        raise RuntimeError('好友页未找到踩踩按钮')

    def _friend_items(self) -> list[tuple[str, int, int]]:
        """当前可见的好友列表项：[(content-desc, 中心x, 中心y)]，按从上到下排序。"""
        els = self.dev.d.xpath(FRIEND_ITEM_XPATH).all()
        items = []
        for e in els:
            left, top, right, bottom = e.bounds
            items.append((e.attrib.get('content-desc', ''),
                          int((left + right) / 2), int((top + bottom) / 2)))
        items.sort(key=lambda it: (it[2], it[1]))
        log('当前可见好友: ' + (', '.join(f'{d}@({x},{y})' for d, x, y in items) or '无'))
        return items

    def _wait_friend_items(self, *, required: bool = False) -> list[tuple[str, int, int]]:
        """等待好友列表渲染；required 时连续为空按异常重试，而非判定列表结束。"""
        attempts = self.wait_attempts(FRIEND_LIST_RETRIES)
        for attempt in range(1, attempts + 1):
            items = self._friend_items()
            if items:
                return items
            if attempt < attempts:
                log(f'好友列表尚未加载，等待重试 ({attempt}/{attempts})')
                time.sleep(CLICK_INTERVAL)
        if required:
            raise RuntimeError('好友列表连续多次为空，无法判断是否还有好友')
        return []

    def next_friend(self, visible: list[tuple[str, int, int]] | None = None) -> bool:
        """切换到下一个好友：按累积名单顺序点下一个。

        好友列表滚动加载，控件树里只有当前可见项：每次重新抓取只把
        新出现的好友追加到累积名单尾部（不删除滚出屏幕的项）。昵称允许
        重复：当右侧候选与已访问好友同名时，按轮播坐标继续前进，不能把
        重复昵称误判成列表结束。点击后必须看到轮播名单或坐标实际变化才
        算切换成功；否则重试，避免一次点击丢失后误判。
        """
        # 调用方刚抓过列表时可传进来复用，避免同一画面连续 dump 两次并重复日志。
        if visible is None:
            visible = self._wait_friend_items(required=True)
        if not self._friends:
            # 第一次把当前可见槽位原样记下，不能按昵称去重：好友允许同名。
            self._current_friend_x = None
            self._friends.extend(desc for desc, _, _ in visible if desc)
            new = list(self._friends)
        else:
            new = [desc for desc, _, _ in visible if desc and desc not in self._friends]
        for desc in new:
            if len(self._friends) == 0 or desc not in self._friends:
                self._friends.append(desc)
        # 好友多时完整累积名单会在每次切换时成倍刷屏。只打印本轮首次出现的
        # 名字；已打印过的名字不再重复，累计数量仍保留用于观察遍历进度。
        if new:
            log(f'新增好友({len(new)}，累计 {len(self._friends)}): ' + ', '.join(new))
        current_desc = (self._friends[self._friend_index]
                        if self._friend_index < len(self._friends) else '')
        current_x = getattr(self, '_current_friend_x', None)
        if current_x is None:
            current_hits = [(x, y) for desc, x, y in visible if desc == current_desc]
            if current_hits:
                # 进入好友页时默认选中最左槽；之后每次成功切换都会记录中心坐标。
                current_x = min(x for x, _ in current_hits)
                self._current_friend_x = current_x
        next_index = self._friend_index + 1
        forced_target = None
        if next_index >= len(self._friends):
            # 没出现“新昵称”不等于没有下一位；右侧可能正好是重名好友。
            right = [(desc, x, y) for desc, x, y in visible
                     if desc and current_x is not None and x > current_x + 20]
            if not right:
                return False
            forced_target = min(right, key=lambda item: item[1])
            self._friends.append(forced_target[0])
        target = self._friends[next_index]
        target_items = ([forced_target] if forced_target else
                        [(desc, x, y) for desc, x, y in visible
                         if desc == target and (current_x is None or x > current_x + 20)])
        if not target_items:
            target_items = [(desc, x, y) for desc, x, y in visible if desc == target]
        for desc, x, y in target_items:
            if desc == target:
                before_names = tuple(item_desc for item_desc, _, _ in visible)
                click_attempts = self.wait_attempts(FRIEND_SWITCH_CLICK_RETRIES)
                poll_attempts = self.wait_attempts(FRIEND_SWITCH_POLL_RETRIES)
                for attempt in range(1, click_attempts + 1):
                    log(f'切换第 {next_index + 1} 个好友: {target} ({x}, {y})')
                    self.click(x, y)
                    for _ in range(poll_attempts):
                        time.sleep(CLICK_INTERVAL)
                        after = self._friend_items()
                        if not after:
                            continue
                        after_names = tuple(item_desc for item_desc, _, _ in after)
                        after_xs = sorted(item_x for _, item_x, _ in after)
                        center_x = after_xs[len(after_xs) // 2]
                        matching_xs = [item_x for item_desc, item_x, _ in after
                                       if item_desc == target]
                        target_x = (min(matching_xs, key=lambda item_x: abs(item_x - center_x))
                                    if matching_xs else None)
                        # 正常选中后目标会向轮播中央移动约 50px，或列表滑出/滑入一人。
                        # 忽略控件边界 1-2px 的轻微抖动，避免把未生效误当作已切换。
                        moved = (after_names != before_names
                                 or (target_x is not None and abs(target_x - x) >= 20))
                        if not moved:
                            continue
                        appeared = [item_desc for item_desc, _, _ in after
                                    if item_desc and item_desc not in self._friends]
                        self._friends.extend(appeared)
                        if appeared:
                            log(f'新增好友({len(appeared)}，累计 {len(self._friends)}): '
                                + ', '.join(appeared))
                        self._friend_index = next_index
                        self._current_friend_x = target_x
                        return True
                    if attempt < click_attempts:
                        log(f'目标 {target} 点击后轮播未移动，重新点击 '
                            f'({attempt}/{click_attempts})')
                raise RuntimeError(f'切换好友 {target} 失败：连续点击后轮播仍未移动')
        raise RuntimeError(f'下一个好友 {target} 当前不可见，无法确认列表已结束')

    def close(self) -> None:
        """关闭好友相关页面：点 back 直到 踩踩/访问/好友列表 都消失。"""
        for _ in range(5):
            source = self.dev.hierarchy()
            if not (self.see('visit_step', source=source)
                    or self.see('visit', source=source)
                    or self.dev.find_xpath_all(FRIEND_ITEM_XPATH, source=source)):
                return
            if not self.go_back(source=source):
                break
            time.sleep(CLICK_INTERVAL)
        log('关闭好友页面失败（可能未回到进入前的页面）')

    def _visit_all(self, max_times: int, today: str, done: int, history: dict) -> int:
        """从好友面板开始踩满剩余次数，期间顺带做经验日常（好友页照顾区域有 exp 就点）。

        踩踩次数已满但经验日常未完成时，仍继续遍历好友做经验照顾，跳过已踩/踩踩判断。
        """
        self._friends = []        # 累积好友名单（content-desc），只增不减
        self._friend_index = 0    # 访问进入时默认第一个好友
        self._exp_handled = False  # 本轮是否处理过经验照顾（点击/判定完成）
        self.goto_first_friend()
        exp_today, exp_done, exp_history = load_exp_daily(quiet=True)
        while True:
            if not max_times or done < max_times:
                # 已踩/踩踩 判断处理
                if self.step_once() == 'already':
                    log('该好友今天已踩过，跳过')
                else:
                    done += 1
                    save_progress(PROGRESS_FILE, today, done, history)
                    log(f'已踩踩 {done} 次' + (f' / 目标 {max_times} 次' if max_times else ''))
            # 切换好友前：经验日常未完成则先处理照顾
            if not exp_done:
                exp_done = self._try_exp_daily(exp_today, exp_history)
            done_full = bool(max_times) and done >= max_times
            if done_full and exp_done:
                break
            if not self.next_friend():
                log('没有更多好友了')
                break
        return done

    def _try_exp_daily(self, exp_today: str, exp_history: dict) -> bool:
        """当前好友宠物页尝试经验日常：有 one_click_care 时 OCR 其父级"照顾区域"，
        含"exp/经验"就点 one_click_care；区域无则视为当日经验日常完成并持久化。
        返回经验日常是否已完成。"""
        # 一次控件树快照复用：one_click_care 和父级 care_region 同一次 dump 里查
        source = self.dev.hierarchy()
        care = self.see('one_click_care', source=source)
        if not care:
            return False  # 没有照顾按钮，跳过（不标记完成）
        bounds = see_bounds(self.dev, 'care_region', source=source)
        if not bounds:
            return False
        x1, y1, x2, y2 = bounds
        results = ocr_texts(self.screen()[y1:y2, x1:x2])
        log('照顾区域 OCR: '
            + (', '.join(f'{t!r}@({x},{y})' for t, x, y, _ in results) or '无'))
        if any(('exp' in (t or '').lower()) or ('经验' in (t or '')) for t, *_ in results):
            log(f'照顾区域含 exp 经验值，点击一键护理 ({care[0]}, {care[1]})')
            self.click(care[0], care[1])
            self._exp_handled = True
            # 支付确认弹窗可能比护理按钮点击晚一拍出现，短等几次再判断（同 care.py）
            for attempt in range(1, ONE_CLICK_PAY_RETRIES + 1):
                pay = self.see('one_click_pay')
                if pay:
                    log(f'检测到"支付并护理"，点击确认 ({pay[0]}, {pay[1]})')
                    self.click(pay[0], pay[1])
                    time.sleep(CLICK_INTERVAL)
                    break
                if attempt < ONE_CLICK_PAY_RETRIES:
                    time.sleep(CLICK_INTERVAL)
            return False
        log('照顾区域无 exp，经验日常已完成')
        save_exp_daily(True, exp_today, exp_history)
        self._exp_handled = True
        return True

    # ---- 入口 ----

    def run(self, max_times: int | None = None, max_rounds: int = 0) -> bool:
        """独立运行：回主页面后进好友面板连续踩满目标，再回主页面。

        max_rounds 参数仅为与其他场景签名一致，踩踩一次调用完成整个会话。
        每次调用代表一次“重新进入”；若持久化进度已达到退出后完成阈值，直接
        收尾，不再重新加载已踩好友。阈值不会中断当前正在运行的 _visit_all。
        返回本次是否踩了至少一次。
        """
        if max_times is None:
            max_times = self.continuous_target
        today, done, history = load_progress(PROGRESS_FILE)
        log_history(history, today)
        log_exp_daily()  # 显示经验日常当天状态与历史
        if visit_finished_after_exit(done, max_times, self.exit_complete_count):
            if max_times and done >= max_times:
                log(f'今天已完成连续踩踩目标 {done}/{max_times}，无需再进入好友列表')
            else:
                log(f'踩踩场景此前已退出，当前 {done} 次达到退出后完成阈值 '
                    f'{self.exit_complete_count}，今日踩踩视为完成')
            # 异常后的 run_one 会立刻再次调用本方法，现场可能仍停在好友页；
            # 在返回 False 前收回主页面，避免调度器把任务标完成后留在错误页面。
            self.close()
            self.ensure_main_page()
            return False
        start_done = done
        self.ensure_main_page()
        done = self._visit_all(max_times, today, done, history)
        self.close()  # 先点 back 收掉好友相关页面，再确认回主页面
        self.ensure_main_page()
        # 踩了或处理过经验照顾（点击/判定完成）都算本轮有产出；
        # 不能把"早已完成的经验日常"算产出——那会让调度器反复重跑踩踩空转
        return done > start_done or self._exp_handled

if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser(description='踩踩场景')
    ap.add_argument('--times', type=int, default=None,
                    help='本次连续踩踩目标，0 为不限；不指定则读 visit.continuous_target')
    args = ap.parse_args()

    try:
        VisitScenario().run(max_times=args.times)
    except KeyboardInterrupt:
        log('手动停止')
