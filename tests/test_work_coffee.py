from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from scenarios.work import WorkScenario
from scenarios.work_coffee import drink_americano_once, find_americano
from src.settings import validate_field


class WorkCoffeeTests(TestCase):
    def make_scenario(self, enabled=True):
        return SimpleNamespace(
            cfg=SimpleNamespace(work=SimpleNamespace(auto_americano=enabled)),
            screen=Mock(return_value=np.zeros((1440, 720, 3), dtype=np.uint8)),
            see=Mock(side_effect=lambda name, screen: {
                'work_in': (178, 999, 1),
                'work_coffee_add_hint': (517, 1153, 1),
                'work_coffee_title': (358, 903, 1),
                'work_coffee_panel': (354, 1282, 1),
            }.get(name)),
            click=Mock(),
        )

    def test_success_counter_closes_menu_and_only_drinks_once(self):
        scen = self.make_scenario()
        with patch('scenarios.work_coffee.find_americano', side_effect=[None, None, (362, 1120)]), \
             patch('scenarios.work_coffee.read_drink_usage', side_effect=[None, (1, 1)]), \
             patch('scenarios.work_coffee.ocr_texts', return_value=[('45', 40, 20, 1)]), \
             patch('scenarios.work_coffee._report') as report, \
             patch('scenarios.work_coffee.time.sleep'):
            drink_americano_once(scen)
            drink_americano_once(scen)
        self.assertEqual([call.args for call in scen.click.call_args_list],
                         [(316, 1169), (362, 1120), (658, 923)])
        report.assert_not_called()

    def test_already_consumed_does_not_click_drink(self):
        scen = self.make_scenario()
        with patch('scenarios.work_coffee.find_americano', return_value=None), \
             patch('scenarios.work_coffee.read_drink_usage', return_value=(1, 1)), \
             patch('scenarios.work_coffee._report') as report, \
             patch('scenarios.work_coffee.time.sleep'):
            drink_americano_once(scen)
        self.assertEqual([call.args for call in scen.click.call_args_list],
                         [(316, 1169), (658, 923)])
        report.assert_not_called()

    def test_waits_for_sliding_panel_and_clicks_current_plus(self):
        for recognize_plus in (False, True):
            with self.subTest(recognize_plus=recognize_plus):
                scen = self.make_scenario()
                working = iter([(178, 1122, 1), (176, 919, 1), (176, 919, 1)])
                hints = iter([(517, 1277, 1), (517, 1074, 1), (517, 1074, 1)])
                pluses = iter([(314, 1293, 1), (314, 1090, 1), (314, 1090, 1)])
                original_see = scen.see.side_effect

                def see(name, screen):
                    if name == 'work_in':
                        return next(working)
                    if name == 'work_coffee_add_hint':
                        return next(hints)
                    if name == 'work_coffee_add' and recognize_plus:
                        return next(pluses)
                    return original_see(name, screen)

                scen.see.side_effect = see
                with patch('scenarios.work_coffee.find_americano',
                           side_effect=[None, None, None, (362, 1120)]), \
                     patch('scenarios.work_coffee.read_drink_usage', side_effect=[None, (1, 1)]), \
                     patch('scenarios.work_coffee.ocr_texts', return_value=[]), \
                     patch('scenarios.work_coffee._report') as report, \
                     patch('scenarios.work_coffee.time.sleep'):
                    drink_americano_once(scen)
                expected = (314, 1090) if recognize_plus else (316, 1089)
                self.assertEqual(scen.click.call_args_list[0].args, expected)
                self.assertEqual(scen.click.call_count, 3)
                report.assert_not_called()

    def test_unsettled_panel_does_not_click_or_repeat(self):
        scen = self.make_scenario()
        working = iter([(178, y, 1) for y in (1122, 1082, 1042, 1002)])
        hints = iter([(517, y + 155, 1) for y in (1122, 1082, 1042, 1002)])
        original_see = scen.see.side_effect

        def see(name, screen):
            if name == 'work_in':
                return next(working)
            if name == 'work_coffee_add_hint':
                return next(hints)
            return original_see(name, screen)

        scen.see.side_effect = see
        with patch('scenarios.work_coffee.find_americano', return_value=None), \
             patch('scenarios.work_coffee._report') as report, \
             patch('scenarios.work_coffee.time.sleep'):
            drink_americano_once(scen)
            drink_americano_once(scen)
        scen.click.assert_not_called()
        report.assert_called_once()

    def test_disabled_does_not_open_menu(self):
        scen = self.make_scenario(False)
        drink_americano_once(scen)
        scen.screen.assert_not_called()
        scen.click.assert_not_called()

    def test_consumption_failure_never_retries(self):
        scen = self.make_scenario()
        with patch('scenarios.work_coffee.find_americano', side_effect=[None, None, (362, 1120), None]), \
             patch('scenarios.work_coffee.read_drink_usage', return_value=None), \
             patch('scenarios.work_coffee.ocr_texts', return_value=[]), \
             patch('scenarios.work_coffee._report') as report, \
             patch('scenarios.work_coffee.time.sleep'):
            drink_americano_once(scen)
            drink_americano_once(scen)
        report.assert_called_once()
        self.assertEqual(sum(call.args == (362, 1120) for call in scen.click.call_args_list), 1)

    def test_zero_inventory_does_not_click_drink(self):
        scen = self.make_scenario()
        with patch('scenarios.work_coffee.find_americano', side_effect=[None, None, (362, 1120)]), \
             patch('scenarios.work_coffee.read_drink_usage', return_value=None), \
             patch('scenarios.work_coffee.ocr_texts', return_value=[('0', 40, 20, 1)]), \
             patch('scenarios.work_coffee._report') as report, \
             patch('scenarios.work_coffee.time.sleep'):
            drink_americano_once(scen)
        self.assertIn('库存为 0', report.call_args.args[1])
        self.assertEqual([call.args for call in scen.click.call_args_list],
                         [(316, 1169), (658, 923)])

    def test_empty_item_menu_is_closed_after_reporting(self):
        scen = self.make_scenario()
        see = scen.see.side_effect
        scen.see.side_effect = lambda name, screen: None if name == 'work_coffee_panel' else see(name, screen)
        with patch('scenarios.work_coffee.find_americano', return_value=None), \
             patch('scenarios.work_coffee._report') as report, \
             patch('scenarios.work_coffee.time.sleep'):
            drink_americano_once(scen)
        report.assert_called_once()
        self.assertEqual([call.args for call in scen.click.call_args_list],
                         [(316, 1169), (658, 923)])

    def test_exception_is_reported_once_and_does_not_fail_work(self):
        scen = self.make_scenario()
        scen.click.side_effect = RuntimeError('click failed')
        with patch('scenarios.work_coffee.find_americano', return_value=None), \
             patch('scenarios.work_coffee._report') as report:
            drink_americano_once(scen)
            drink_americano_once(scen)
        report.assert_called_once()
        self.assertTrue(scen._coffee_attempted)

    def test_color_detection_accepts_large_and_small_cup(self):
        for size in (20, 60):
            screen = np.zeros((1440, 720, 3), dtype=np.uint8)
            screen[1030:1030 + size, 340:340 + size] = (140, 42, 8)
            screen[1030:1040, 340:340 + size] = (240, 240, 240)
            self.assertIsNotNone(find_americano(screen, anchor_y=903))
        empty = np.zeros((1440, 720, 3), dtype=np.uint8)
        self.assertIsNone(find_americano(empty, anchor_y=903))

    def test_start_hook_requires_clicking_new_work(self):
        scen = WorkScenario.__new__(WorkScenario)
        scen.handle_low_stat_dialog = Mock()
        scen.screen = Mock()
        scen.click = Mock()
        with patch('scenarios.work.ocr_fullscreen', side_effect=[
                [('去打工', 350, 1200, 1)], [('正在打工', 170, 999, 1)]]), \
             patch('scenarios.work.drink_americano_once') as drink, \
             patch('scenarios.work.time.sleep'):
            scen._start_work()
            drink.assert_called_once_with(scen)
        with patch('scenarios.work.ocr_fullscreen', return_value=[('正在打工', 170, 999, 1)]), \
             patch('scenarios.work.drink_americano_once') as drink:
            scen._start_work()
            drink.assert_not_called()

    def test_setting_requires_boolean(self):
        self.assertEqual(validate_field('work.auto_americano', True), (True, True))
        self.assertEqual(validate_field('work.auto_americano', 'false'), (False, False))
