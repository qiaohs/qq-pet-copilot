from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from src.locators import LOCATORS, _locate
from src.scenario import DeviceScenario


class ActivityProgressTests(TestCase):
    def make_scenario(self):
        scen = DeviceScenario.__new__(DeviceScenario)
        scen.cfg = SimpleNamespace(schedule=SimpleNamespace(check_interval=1, encourage_times=12))
        scen.snapshot = Mock(return_value=('image', 'source'))
        scen.read_remaining_seconds = Mock(return_value=2640)
        scen._encourage_burst = Mock(return_value=12)
        scen.ensure_main_page = Mock()
        scen.leave_home = Mock()
        scen.close_activity_settlement = Mock()
        scen.pending = None
        return scen

    def test_active_class_and_work_register_pending_without_counting(self):
        for kind in ('school', 'work'):
            for already_encouraged in (False, True):
                with self.subTest(kind=kind, already_encouraged=already_encouraged):
                    scen = self.make_scenario()
                    scen.see = Mock(side_effect=lambda name, *args:
                                    (20, 900, 1) if name.endswith('_in') else None)
                    scen.wait_end = Mock()
                    counted = Mock()
                    self.assertTrue(scen.defer_busy_end(
                        f'{kind}_in', f'{kind}_end', counted, kind, encourage=True,
                        encourage_on_start=not already_encouraged))
                    counted.assert_not_called()
                    scen.wait_end.assert_not_called()
                    self.assertEqual(scen._encourage_burst.call_count, int(not already_encouraged))
                    self.assertTrue(scen.pending['encourage'])
                    self.assertGreater(scen.pending['until'], datetime.now() + timedelta(minutes=43))

    def test_real_settlement_still_finishes_once(self):
        scen = self.make_scenario()
        scen.see = Mock(side_effect=lambda name, *args: (20, 900, 1) if name == 'school_end' else None)
        scen.wait_end = Mock()
        counted = Mock()
        self.assertFalse(scen.defer_busy_end('school_in', 'school_end', counted, '上课'))
        counted.assert_called_once()
        scen.wait_end.assert_called_once()
        self.assertIsNone(scen.pending)

    def test_pending_active_class_reestimates_without_finishing(self):
        scen = self.make_scenario()
        scen.see = Mock(side_effect=lambda name, *args:
                        (20, 900, 1) if name == 'school_in' else None)
        counted = Mock()
        scen.pending = dict(in_name='school_in', end_name='school_end',
                            desc='上课', encourage=True, on_finish=counted)
        self.assertFalse(scen.finish_pending())
        counted.assert_not_called()
        scen.close_activity_settlement.assert_not_called()
        scen._encourage_burst.assert_called_once()
        self.assertIsNotNone(scen.pending)

    def test_blocking_wait_does_not_end_while_active_marker_remains(self):
        scen = self.make_scenario()
        scen.dev = SimpleNamespace(click=Mock())
        ended = iter([None, (30, 950, 1)])
        scen.see = Mock(side_effect=lambda name, *args:
                        next(ended) if name == 'work_end' else (20, 900, 1))
        with patch('src.scenario.time.sleep') as sleep:
            scen.wait_end('work_in', 'work_end', encourage=True)
        self.assertEqual(scen.snapshot.call_count, 2)
        sleep.assert_called_once_with(1)
        scen.close_activity_settlement.assert_called_once()

    def test_progress_banner_with_share_is_not_adventure_settlement(self):
        scen = self.make_scenario()
        scen.see = Mock(return_value=(20, 900, 1))
        for text in ('正在学习', '学习中', '正在打工', '打工中'):
            with self.subTest(text=text), patch('src.scenario.ocr_screen',
                    return_value=[(text, 200, 300, 1), ('分享', 400, 100, 1)]):
                self.assertIsNone(scen._detect_settlement('image', 'source'))
        scen.see.assert_not_called()

    def test_school_and_work_end_locators_require_settlement_content(self):
        dev = SimpleNamespace(find_xpath=Mock(side_effect=lambda path, source:
                              (20, 100) if '分享' in path else None))
        screen = np.zeros((1440, 720, 3), dtype=np.uint8)
        for kind, text in (('school', '宠物成绩单'), ('school', '教师评语'),
                           ('school', '继续学习'), ('work', '打工总结')):
            with self.subTest(kind=kind, text=text):
                with patch('src.locators._ocr_texts_cached', return_value=[('分享', 20, 100, 1)]):
                    self.assertIsNone(_locate(dev, LOCATORS[f'{kind}_end'], screen, 'source'))
                with patch('src.locators._ocr_texts_cached', return_value=[(text, 200, 900, 1)]):
                    self.assertIsNotNone(_locate(dev, LOCATORS[f'{kind}_end'], screen, 'source'))

    def test_encouragement_returns_count_for_startup_deduplication(self):
        scen = self.make_scenario()
        scen.see = Mock(return_value=(635, 300, 1))
        scen.click = Mock()
        with patch('src.scenario.time.sleep'):
            self.assertEqual(DeviceScenario._encourage_burst(scen), 12)
        self.assertEqual(scen.click.call_count, 12)
        scen.cfg.schedule.encourage_times = 0
        self.assertEqual(DeviceScenario._encourage_burst(scen), 0)
