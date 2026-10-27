from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from scenarios.school_milk import drink_milk_once, find_yellow_milk
from scenarios.school import SchoolScenario
from src.settings import validate_field


class SchoolMilkTest(TestCase):
    def make_scenario(self, enabled=True):
        scen = SimpleNamespace(
            cfg=SimpleNamespace(school=SimpleNamespace(auto_calcium_milk=enabled)),
            screen=Mock(return_value=np.zeros((1440, 720, 3), dtype=np.uint8)),
            see=Mock(return_value=(360, 922, 1)),
            click=Mock(),
        )
        return scen

    def test_yellow_milk_can_be_large_or_small_and_blue_is_excluded(self):
        for size in (20, 60):
            with self.subTest(size=size):
                screen = np.zeros((1440, 720, 3), dtype=np.uint8)
                screen[1080:1080 + size, 350:350 + size] = (255, 255, 220)
                screen[1080:1090, 350:350 + size] = (255, 205, 30)
                screen[1060:1190, 550:660] = (70, 170, 255)
                point = find_yellow_milk(screen)
                self.assertIsNotNone(point)
                self.assertLess(point[0], 500)
        screen[:, :500] = 0
        self.assertIsNone(find_yellow_milk(screen))

    def test_disabled_does_not_open_menu(self):
        scen = self.make_scenario(enabled=False)
        drink_milk_once(scen)
        scen.screen.assert_not_called()
        scen.click.assert_not_called()

    def test_uncertain_result_is_reported_once_and_never_clicked_again(self):
        scen = self.make_scenario()
        with patch('scenarios.school_milk.find_yellow_milk',
                   side_effect=[None, (350, 1053), None]), \
                patch('scenarios.school_milk._report') as report, \
                patch('src.ocr.ocr_texts', return_value=[]), \
                patch('scenarios.school_milk.time.sleep'):
            drink_milk_once(scen)
            clicks = list(scen.click.call_args_list)
            drink_milk_once(scen)
        report.assert_called_once()
        self.assertEqual(scen.click.call_args_list, clicks)
        self.assertEqual(sum(call.args == (350, 1053) for call in clicks), 1)
        self.assertTrue(scen._milk_attempted)

    def test_zero_stock_reports_and_does_not_click_milk(self):
        scen = self.make_scenario()
        with patch('scenarios.school_milk.find_yellow_milk',
                   side_effect=[None, (350, 1053)]), \
                patch('scenarios.school_milk._report') as report, \
                patch('src.ocr.ocr_texts', return_value=[('0', 0, 0, 1)]), \
                patch('scenarios.school_milk.time.sleep'):
            drink_milk_once(scen)
        self.assertIn('库存为 0', report.call_args.args[1])
        self.assertNotIn((350, 1053), [call.args for call in scen.click.call_args_list])

    def test_click_failure_is_not_propagated_to_learning_retry(self):
        scen = self.make_scenario()
        scen.click.side_effect = RuntimeError('点击超时')
        with patch('scenarios.school_milk.find_yellow_milk', return_value=None), \
                patch('scenarios.school_milk._report') as report:
            drink_milk_once(scen)
            drink_milk_once(scen)
        scen.click.assert_called_once()
        report.assert_called_once()

    def test_new_class_calls_milk_once_before_registering_pending(self):
        scen = SchoolScenario.__new__(SchoolScenario)
        scen.defer_wait = True
        scen.select_course = Mock()
        scen.click_until_gone_or_see = Mock()
        scen._detect_duration_from_remaining = Mock()
        scen.defer_busy_end = Mock()
        scen.ensure_main_page = Mock()
        events = []
        scen.click_until_gone_or_see.side_effect = lambda *args: events.append('started')
        scen.defer_busy_end.side_effect = lambda *args, **kwargs: events.append('pending')
        with patch('scenarios.school.drink_milk_once',
                   side_effect=lambda _scen: events.append('milk')) as drink:
            scen.attend_class()
        drink.assert_called_once_with(scen)
        self.assertEqual(events, ['started', 'milk', 'pending'])

    def test_milk_setting_requires_boolean(self):
        self.assertEqual(validate_field('school.auto_calcium_milk', True), (True, True))
        self.assertEqual(validate_field('school.auto_calcium_milk', 'false'), (False, False))
