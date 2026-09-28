from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import tempfile

from scenarios.friend_care import FriendCareScenario
from scenarios.hire_friend import FriendHireScenario, FriendUnavailable
from scenarios.friend_features import (
    LUCKY_BAG_ABSENT,
    LUCKY_BAG_CLAIMED,
    LUCKY_BAG_UNOPENED,
    claim_lucky_bag,
    lucky_bag_state,
)
from scenarios.visit import VisitScenario
from main import ScrcpyContainer
from src.scenario import TaskDeferred
from scenarios.care import CareScenario
from scenarios.runner import TaskQueueRunner, _QueueTask
from src import progress, progress_store
from src.coins import read_coins_from_ocr
from src.config import TaskItemConfig
from src.adb.device import Device


class CustomChangesTest(TestCase):
    def test_gui_screenshot_uses_valid_adb_png(self):
        dev = Device.__new__(Device)
        dev.ensure_connected = lambda: 'serial'
        png = b'\x89PNG\r\n\x1a\ncontent'
        dev._run = lambda *_args: SimpleNamespace(stdout=png)
        self.assertEqual(dev.screenshot_png(), png)

    def test_lucky_bag_recognizes_glow_and_claimed_bag(self):
        import cv2
        import numpy as np

        unopened_hsv = np.zeros((1440, 720, 3), dtype=np.uint8)
        unopened_hsv[900:980, 80:110] = (25, 180, 230)
        unopened = cv2.cvtColor(unopened_hsv, cv2.COLOR_HSV2RGB)
        self.assertEqual(lucky_bag_state(unopened), LUCKY_BAG_UNOPENED)

        # 回归：暖色地板/发光宠物窝可能面积很大，但形状是横向扁块，不是福袋光晕。
        floor_hsv = np.zeros((1440, 720, 3), dtype=np.uint8)
        floor_hsv[964:1008, 67:159] = (25, 180, 230)
        floor = cv2.cvtColor(floor_hsv, cv2.COLOR_HSV2RGB)
        self.assertEqual(lucky_bag_state(floor), LUCKY_BAG_ABSENT)

        claimed_hsv = np.zeros((1440, 720, 3), dtype=np.uint8)
        claimed_hsv[895:920, 90:120] = (10, 180, 180)
        claimed = cv2.cvtColor(claimed_hsv, cv2.COLOR_HSV2RGB)
        self.assertEqual(lucky_bag_state(claimed), LUCKY_BAG_CLAIMED)

    def test_lucky_bag_closes_possible_popup_by_shadow_click(self):
        import numpy as np

        scen = SimpleNamespace()
        scen.screen = lambda: np.zeros((1440, 720, 3), dtype=np.uint8)
        clicks = []
        scen.click = lambda x, y: clicks.append((x, y))
        with patch('scenarios.friend_features.lucky_bag_state',
                   side_effect=[LUCKY_BAG_UNOPENED, LUCKY_BAG_CLAIMED]), \
                patch('scenarios.friend_features.time.sleep'):
            self.assertEqual(claim_lucky_bag(scen, '好友'), LUCKY_BAG_CLAIMED)
        self.assertEqual(clicks[0], (112, 950))
        self.assertEqual(clicks[1], (18, 691))
        self.assertEqual(clicks[2], (18, 691))

    def test_visit_reentry_above_threshold_finishes_without_reloading_list(self):
        scen = VisitScenario.__new__(VisitScenario)
        scen.continuous_target = 950
        scen.exit_complete_count = 200
        closed = []
        main_page = []
        scen.close = lambda: closed.append(True)
        scen.ensure_main_page = lambda: main_page.append(True)
        scen._visit_all = lambda *_args: self.fail('达到退出阈值后不应重新进入好友列表')

        with patch('scenarios.visit.load_progress',
                   return_value=(progress_store.today_str(), 200, {})), \
                patch('scenarios.visit.log_history'), \
                patch('scenarios.visit.log_exp_daily'):
            self.assertFalse(scen.run())
        self.assertEqual(len(closed), 1)
        self.assertEqual(len(main_page), 1)

    def test_next_friend_retries_until_carousel_really_moves(self):
        scen = VisitScenario.__new__(VisitScenario)
        scen._friends = ['好友 A', '好友 B']
        scen._friend_index = 0
        scen.wait_attempts = lambda value: value
        before = [('好友 A', 78, 1255), ('好友 B', 465, 1255)]
        moved = [('好友 A', 78, 1255), ('好友 B', 269, 1255),
                 ('好友 C', 465, 1255)]
        frames = iter([before, before, moved])
        scen._friend_items = lambda: next(frames)
        clicks = []
        scen.click = lambda x, y: clicks.append((x, y))

        with patch('scenarios.visit.time.sleep'):
            self.assertTrue(scen.next_friend(before))
        self.assertEqual(clicks, [(465, 1255), (465, 1255)])
        self.assertEqual(scen._friend_index, 1)
        self.assertEqual(scen._friends, ['好友 A', '好友 B', '好友 C'])

    def test_visit_current_session_ignores_exit_threshold_and_targets_950(self):
        scen = VisitScenario.__new__(VisitScenario)
        scen.continuous_target = 950
        scen.exit_complete_count = 200
        scen._exp_handled = False
        targets = []
        scen.ensure_main_page = lambda: None
        scen.close = lambda: None
        scen._visit_all = lambda target, *_args: targets.append(target) or 950

        with patch('scenarios.visit.load_progress',
                   return_value=(progress_store.today_str(), 199, {})), \
                patch('scenarios.visit.log_history'), \
                patch('scenarios.visit.log_exp_daily'):
            self.assertTrue(scen.run())
        self.assertEqual(targets, [950])

    def test_visit_scheduler_does_not_reenter_after_exit_threshold(self):
        runner = TaskQueueRunner.__new__(TaskQueueRunner)
        runner.visit_times = 950
        runner.visit_exit_complete_count = 200
        runner.visit_start = datetime(2000, 1, 1, 0, 0).time()
        runner.retry_after = {}
        with patch('scenarios.runner.load_progress',
                   return_value=(progress_store.today_str(), 200, {})):
            self.assertFalse(runner.visit_due())

    def test_scrcpy_fit_uses_native_client_pixels(self):
        fake = SimpleNamespace(
            _hwnd=123,
            _aspect=(9, 16),
            _native_client_size=lambda: (900, 1800),
        )
        with patch('main.win32gui.MoveWindow') as move:
            ScrcpyContainer._fit(fake)
        move.assert_called_once_with(123, 0, 100, 900, 1600, True)

    def test_scrcpy_compact_size_is_distinct_from_fit_mode(self):
        hint = ScrcpyContainer.sizeHint(None)
        self.assertEqual((hint.width(), hint.height()), (252, 448))

    def test_rest_window_supports_normal_and_cross_midnight_ranges(self):
        runner = TaskQueueRunner.__new__(TaskQueueRunner)
        rest1 = _QueueTask('rest1')
        rest1.cfg = TaskItemConfig(enabled=True, enabled_time_range='19:46-19:58')
        rest2 = _QueueTask('rest2')
        rest2.cfg = TaskItemConfig(enabled=False, enabled_time_range='23:50-00:10')
        tasks = {'rest1': rest1, 'rest2': rest2}

        active = runner._active_rest(tasks, ['rest1', 'rest2'],
                                     datetime(2026, 9, 27, 19, 50))
        self.assertEqual(active[0].key, 'rest1')
        self.assertEqual(active[1], datetime(2026, 9, 27, 19, 58))
        self.assertIsNone(runner._active_rest(
            tasks, ['rest1', 'rest2'], datetime(2026, 9, 27, 19, 58)))

        rest1.cfg.enabled = False
        rest2.cfg.enabled = True
        active = runner._active_rest(tasks, ['rest1', 'rest2'],
                                     datetime(2026, 9, 27, 23, 55))
        self.assertEqual(active[1], datetime(2026, 9, 28, 0, 10))

    def test_care_runs_before_rest_and_rest_blocks_employed_check(self):
        runner = TaskQueueRunner.__new__(TaskQueueRunner)
        runner._active_rest_key = None
        runner._rest_until = None
        runner._current_task = None
        runner._pending_finish_first = lambda: None
        runner._eligible = lambda task, now: task.cfg.enabled
        care = _QueueTask('care')
        friend = _QueueTask('friend_care')
        rest = _QueueTask('rest1')
        rest.cfg = TaskItemConfig(enabled=True, enabled_time_range='00:00-00:00')
        tasks = {'care': care, 'friend_care': friend, 'rest1': rest}
        order = ['care', 'friend_care', 'rest1']
        executed = []
        runner._execute = lambda task, *_args: executed.append(task.key)
        runner._task_due = lambda key, *_args: key == 'care'
        employed_checks = []
        runner.employed_due = lambda: employed_checks.append(True) or False

        self.assertTrue(runner._run_first_due(tasks, order))
        self.assertEqual(executed, ['care'])
        self.assertEqual(employed_checks, [])

        runner._task_due = lambda *_args: False
        self.assertFalse(runner._run_first_due(tasks, order))
        self.assertEqual(runner._current_task, '休息1')
        self.assertEqual(employed_checks, [])

    def test_coin_reader_uses_rightmost_top_bar_number(self):
        results = [
            ('14', 198, 218, 0.9),
            ('354', 388, 218, 0.9),
            ('1.1w', 521, 220, 0.9),
        ]
        self.assertEqual(read_coins_from_ocr(results), 11000)

    def test_status_reader_reclicks_once_when_panel_never_opened(self):
        scen = CareScenario.__new__(CareScenario)
        reads = iter(({}, {}, {'体力': 96, '清洁': 74, '金币': 11000}))
        scen.snapshot = lambda: (object(), object())

        def read_status(_screen, _source):
            status = next(reads)
            scen._status_panel_visible = '体力' in status
            return status

        scen.read_status = read_status
        clicks = []
        scen.toggle_status = lambda source=None: clicks.append(source)
        with patch('scenarios.care.time.sleep'):
            status = scen.read_status_ready()
        self.assertEqual(status['体力'], 96)
        self.assertEqual(len(clicks), 1)

    def test_advanced_school_legacy_30_or_150_is_repaired_to_135(self):
        for old_minutes in (30, 150):
            with self.subTest(old_minutes=old_minutes), tempfile.TemporaryDirectory() as tmp:
                school_file = Path(tmp) / 'school.json'
                work_file = Path(tmp) / 'work.json'
                progress_store.write_raw(school_file, {
                    'date': progress_store.today_str(),
                    'learned': 1,
                    'school': '高级学园',
                    'study_secs': old_minutes * 60,
                })
                with patch.object(progress, 'SCHOOL_PROGRESS_FILE', school_file), \
                        patch.object(progress, 'WORK_PROGRESS_FILE', work_file):
                    study_secs, _ = progress.load_durations()
                self.assertEqual(study_secs, 135 * 60)
                saved = progress_store.read_raw(school_file)
                self.assertEqual(saved['duration_minutes'], 135)

    def test_custom_study_duration_is_persisted_for_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            school_file = Path(tmp) / 'school.json'
            with patch.object(progress, 'SCHOOL_PROGRESS_FILE', school_file):
                progress.set_current_school('高级学园', 123)
                total = progress.record_study_finish()
            self.assertEqual(total, 123 * 60)

    def test_friend_care_uses_list_order_and_enters_once(self):
        scen = FriendCareScenario.__new__(FriendCareScenario)
        scen.cfg = SimpleNamespace(friend_care=SimpleNamespace(
            enabled=True,
            friend_name='qq1,qq2',
            method='ocr检测',
            energy_target=70,
            clean_target=90,
            time_range='00:00-00:00',
        ), lucky_bag=SimpleNamespace(friend_enabled=False),
            friend_navigation=SimpleNamespace(stop_at_non_friend=False,
                                              min_scan_count=10))
        state = {'index': 0, 'begins': 0, 'closes': 0}
        friends = ['好友 qq2', '好友 其他人', '好友 qq1']
        cared = []
        scen.ensure_main_page = lambda: None
        scen.wait_attempts = lambda value: 1
        scen.begin_friend_walk = lambda: state.__setitem__('begins', state['begins'] + 1)
        scen.current_friend = lambda: (friends[state['index']], [])

        def next_friend(_visible):
            state['index'] += 1
            return state['index'] < len(friends)

        scen.next_friend = next_friend
        scen.close = lambda: state.__setitem__('closes', state['closes'] + 1)
        scen.care_friend = lambda: cared.append(friends[state['index']]) or True

        self.assertTrue(scen.run())
        self.assertEqual(cared, ['好友 qq2', '好友 qq1'])
        self.assertEqual(state['begins'], 1)
        self.assertEqual(state['closes'], 1)

    def test_hire_uses_first_available_configured_friend_in_list_order(self):
        scen = FriendHireScenario.__new__(FriendHireScenario)
        scen.cfg = SimpleNamespace(hire_friend=SimpleNamespace(
            enabled=True,
            friend_name='qq1,qq2',
            times_per_day=1,
        ), friend_navigation=SimpleNamespace(stop_at_non_friend=False,
                                             min_scan_count=10))
        scen.defer_wait = True
        state = {'index': 0, 'begins': 0}
        friends = ['好友 qq2', '好友 qq1']
        selected = []
        scen.ensure_main_page = lambda: None
        scen.detect_busy_remaining = lambda: None
        scen.begin_friend_walk = lambda: state.__setitem__('begins', state['begins'] + 1)
        scen.current_friend = lambda: (friends[state['index']], [])
        scen.next_friend = lambda _visible: False
        scen.wait_hire_ready = lambda: selected.append(friends[state['index']])
        scen._enter_work_panel = lambda: None
        scen._hire_and_work = lambda panel_ready=False: None

        with patch('scenarios.hire_friend.load_progress',
                   return_value=(progress_store.today_str(), 0, {})), \
                patch('scenarios.hire_friend.log_history'):
            self.assertTrue(scen.run())
        self.assertEqual(selected, ['好友 qq2'])
        self.assertEqual(state['begins'], 1)

    def test_hire_unchanged_friend_page_is_not_work_panel(self):
        scen = FriendHireScenario.__new__(FriendHireScenario)
        scen.dev = SimpleNamespace(hierarchy=lambda: '<friend-page/>')
        scen.wait_attempts = lambda _value: 1
        scen.click = lambda *_args: None
        scen.dismiss_career_popup = lambda: False

        def see(name, source=None):
            # 好友页轮播会误命中 select_box；hire 仍在才是决定性证据。
            return (10, 10) if name in ('hire', 'select_box_1') else None

        scen.see = see
        with patch('scenarios.hire_friend.time.sleep'):
            with self.assertRaises(FriendUnavailable):
                scen._enter_work_panel()

    def test_hire_counts_one_failure_after_all_candidates_unavailable(self):
        scen = FriendHireScenario.__new__(FriendHireScenario)
        scen.cfg = SimpleNamespace(hire_friend=SimpleNamespace(
            enabled=True,
            friend_name='qq1,qq2',
            max_scan_count=20,
            times_per_day=1,
        ), friend_navigation=SimpleNamespace(stop_at_non_friend=False,
                                             min_scan_count=10))
        scen.defer_wait = True
        friends = ['好友 qq1', '好友 qq2']
        state = {'index': 0}
        scen.ensure_main_page = lambda: None
        scen.detect_busy_remaining = lambda: None
        scen.begin_friend_walk = lambda: None
        scen.current_friend = lambda: (friends[state['index']], [])
        scen.next_friend = lambda _visible: state.__setitem__('index', 1) or True
        scen.wait_hire_ready = lambda: (_ for _ in ()).throw(FriendUnavailable('CD 未结束'))
        scen._enter_work_panel = lambda: self.fail('CD 未结束时不应点击 hire')
        scen.close = lambda: None

        with patch('scenarios.hire_friend.load_progress',
                   return_value=(progress_store.today_str(), 0, {})), \
                patch('scenarios.hire_friend.log_history'), \
                patch('scenarios.hire_friend.increment_progress', return_value=1) as failed:
            with self.assertRaises(TaskDeferred):
                scen.run()
        failed.assert_called_once()
        self.assertEqual(state['index'], 1)

    def test_friend_care_stops_after_configured_scan_limit(self):
        scen = FriendCareScenario.__new__(FriendCareScenario)
        scen.cfg = SimpleNamespace(friend_care=SimpleNamespace(
            enabled=True,
            friend_name='不存在的好友',
            method='ocr检测',
            energy_target=40,
            clean_target=80,
            max_scan_count=3,
            time_range='00:00-00:00',
        ), lucky_bag=SimpleNamespace(friend_enabled=False),
            friend_navigation=SimpleNamespace(stop_at_non_friend=False,
                                              min_scan_count=10))
        state = {'index': 0, 'closes': 0}
        friends = [f'好友 路人{i}' for i in range(10)]
        scen.ensure_main_page = lambda: None
        scen.wait_attempts = lambda value: 1
        scen.begin_friend_walk = lambda: None
        scen.current_friend = lambda: (friends[state['index']], [])

        def next_friend(_visible):
            state['index'] += 1
            return state['index'] < len(friends)

        scen.next_friend = next_friend
        scen.close = lambda: state.__setitem__('closes', state['closes'] + 1)
        scen.care_friend = lambda: self.fail('不应护理非目标好友')

        self.assertTrue(scen.run())
        self.assertEqual(state['index'], 2)
        self.assertEqual(state['closes'], 1)

    def test_hire_stops_after_configured_scan_limit(self):
        scen = FriendHireScenario.__new__(FriendHireScenario)
        scen.cfg = SimpleNamespace(hire_friend=SimpleNamespace(
            enabled=True,
            friend_name='不存在的好友',
            max_scan_count=3,
            times_per_day=1,
        ), friend_navigation=SimpleNamespace(stop_at_non_friend=False,
                                             min_scan_count=10))
        scen.defer_wait = True
        state = {'index': 0, 'closes': 0}
        friends = [f'好友 路人{i}' for i in range(10)]
        scen.ensure_main_page = lambda: None
        scen.detect_busy_remaining = lambda: None
        scen.begin_friend_walk = lambda: None
        scen.current_friend = lambda: (friends[state['index']], [])

        def next_friend(_visible):
            state['index'] += 1
            return state['index'] < len(friends)

        scen.next_friend = next_friend
        scen.close = lambda: state.__setitem__('closes', state['closes'] + 1)

        with patch('scenarios.hire_friend.load_progress',
                   return_value=(progress_store.today_str(), 0, {})), \
                patch('scenarios.hire_friend.log_history'), \
                patch('scenarios.hire_friend.increment_progress', return_value=1) as failed:
            with self.assertRaises(TaskDeferred):
                scen.run()
        failed.assert_called_once()
        self.assertEqual(state['index'], 2)
        self.assertEqual(state['closes'], 1)

    def test_friend_care_stops_at_non_friend_only_after_minimum_scan(self):
        scen = FriendCareScenario.__new__(FriendCareScenario)
        scen.cfg = SimpleNamespace(
            friend_care=SimpleNamespace(
                enabled=True, friend_name='不存在', method='ocr检测',
                energy_target=70, clean_target=90, max_scan_count=20,
                time_range='00:00-00:00'),
            lucky_bag=SimpleNamespace(friend_enabled=False),
            friend_navigation=SimpleNamespace(stop_at_non_friend=True,
                                              min_scan_count=10))
        state = {'index': 0, 'closed': 0}
        friends = [f'好友 {i}' for i in range(20)]
        scen.ensure_main_page = lambda: None
        scen.wait_attempts = lambda value: 1
        scen.begin_friend_walk = lambda: None
        scen.current_friend = lambda: (friends[state['index']], [])
        scen.screen = lambda: object()
        scen.next_friend = lambda _visible: state.__setitem__('index', state['index'] + 1) or True
        scen.close = lambda: state.__setitem__('closed', state['closed'] + 1)
        with patch('scenarios.friend_care.is_non_friend_page',
                   side_effect=lambda _screen: state['index'] >= 4):
            self.assertTrue(scen.run())
        self.assertEqual(state['index'], 9)
        self.assertEqual(state['closed'], 1)

    def test_hire_stops_at_non_friend_after_minimum_scan_and_counts_once(self):
        scen = FriendHireScenario.__new__(FriendHireScenario)
        scen.cfg = SimpleNamespace(
            hire_friend=SimpleNamespace(
                enabled=True, friend_name='不存在', max_scan_count=20,
                times_per_day=1),
            friend_navigation=SimpleNamespace(stop_at_non_friend=True,
                                              min_scan_count=10))
        scen.defer_wait = True
        state = {'index': 0}
        friends = [f'好友 {i}' for i in range(20)]
        scen.ensure_main_page = lambda: None
        scen.detect_busy_remaining = lambda: None
        scen.begin_friend_walk = lambda: None
        scen.current_friend = lambda: (friends[state['index']], [])
        scen.screen = lambda: object()
        scen.next_friend = lambda _visible: state.__setitem__('index', state['index'] + 1) or True
        scen.close = lambda: None
        with patch('scenarios.hire_friend.load_progress',
                   return_value=(progress_store.today_str(), 0, {})), \
                patch('scenarios.hire_friend.log_history'), \
                patch('scenarios.hire_friend.is_non_friend_page',
                      side_effect=lambda _screen: state['index'] >= 4), \
                patch('scenarios.hire_friend.increment_progress', return_value=1) as failed:
            with self.assertRaises(TaskDeferred):
                scen.run()
        self.assertEqual(state['index'], 9)
        failed.assert_called_once()
