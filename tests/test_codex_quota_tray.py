import unittest
from unittest.mock import patch

import codex_quota_tray as app


class QuotaStateTests(unittest.TestCase):
    def setUp(self):
        with app.lock:
            app.state.clear()
            app.state.update(
                ok=False,
                stale=False,
                error="",
                plan="-",
                primary=None,
                secondary=None,
                credits=None,
                updated=0,
            )
        app.SHOW_MODE = "used"

    def test_weekly_window_uses_weekly_label(self):
        self.assertEqual(
            app.quota_label({"limit_window_seconds": 604800}),
            "每周",
        )

    def test_unknown_window_uses_generic_label(self):
        self.assertEqual(
            app.quota_label({"limit_window_seconds": 1234}),
            "额度",
        )

    def test_failed_refresh_marks_successful_data_stale(self):
        with app.lock:
            app.state.update(
                ok=True,
                stale=False,
                primary={"used_percent": 6},
                updated=100,
            )

        app.set_fetch_error("offline")

        with app.lock:
            self.assertFalse(app.state["ok"])
            self.assertTrue(app.state["stale"])
            self.assertEqual(app.state["error"], "offline")
            self.assertEqual(app.state["updated"], 100)

    def test_title_handles_missing_primary(self):
        with app.lock:
            app.state.update(ok=True, stale=False, primary=None, error="")

        self.assertIn("暂无额度数据", app.make_title())

    def test_display_percent_clamps_malformed_server_values(self):
        self.assertEqual(app.display_percent({"used_percent": 140}, "used"), 100.0)
        self.assertEqual(app.display_percent({"used_percent": -4}, "free"), 100.0)
        self.assertIsNone(app.display_percent({"used_percent": "6"}, "used"))


class OverlayLogicTests(unittest.TestCase):
    def test_layout_cycle_visits_all_three_layouts(self):
        self.assertEqual(app.next_layout("full"), "micro")
        self.assertEqual(app.next_layout("micro"), "vertical")
        self.assertEqual(app.next_layout("vertical"), "full")

    def test_invalid_layout_cycles_to_full(self):
        self.assertEqual(app.next_layout("unknown"), "full")

    def test_visible_saved_position_is_preserved(self):
        areas = [(0, 0, 1920, 1040), (1920, 0, 3200, 720)]
        self.assertEqual(
            app.clamp_overlay_position(2100, 20, 300, 100, areas),
            (2100, 20),
        )

    def test_offscreen_position_falls_back_to_primary_top_left(self):
        areas = [(0, 0, 1920, 1040)]
        self.assertEqual(
            app.clamp_overlay_position(4000, 50, 300, 100, areas),
            (12, 12),
        )

    def test_partially_visible_position_is_preserved(self):
        areas = [(0, 0, 1920, 1040)]
        self.assertEqual(
            app.clamp_overlay_position(-100, 20, 300, 100, areas),
            (-100, 20),
        )

    def test_registry_settings_restore_overlay_behavior(self):
        stored = {
            "layout": "vertical",
            "x": 2100,
            "y": 22,
            "topmost": 0,
            "click_through": 1,
            "overlay_visible": 1,
            "show_mode": "free",
        }

        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def query_value(_key, name):
            if name not in stored:
                raise OSError(name)
            return stored[name], app.winreg.REG_SZ

        with patch.object(app.winreg, "OpenKey", return_value=FakeKey()), patch.object(
            app.winreg, "QueryValueEx", side_effect=query_value
        ):
            settings = app.load_settings()

        self.assertEqual(settings["layout"], "vertical")
        self.assertEqual((settings["x"], settings["y"]), (2100, 22))
        self.assertFalse(settings["topmost"])
        self.assertTrue(settings["click_through"])
        self.assertEqual(settings["show_mode"], "free")

    def test_invalid_registry_values_fall_back_to_safe_defaults(self):
        stored = {"layout": "giant", "x": "left", "show_mode": "remaining"}

        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def query_value(_key, name):
            if name not in stored:
                raise OSError(name)
            return stored[name], app.winreg.REG_SZ

        with patch.object(app.winreg, "OpenKey", return_value=FakeKey()), patch.object(
            app.winreg, "QueryValueEx", side_effect=query_value
        ):
            settings = app.load_settings()

        self.assertEqual(settings["layout"], "full")
        self.assertEqual(settings["x"], 12)
        self.assertEqual(settings["show_mode"], "used")


class DisplayRowTests(unittest.TestCase):
    def test_single_weekly_window_builds_one_row(self):
        rows = app.make_display_rows(
            {
                "limit_window_seconds": 604800,
                "used_percent": 6,
                "reset_after_seconds": 600000,
            },
            None,
            "used",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "每周")
        self.assertEqual(rows[0]["percent"], 6.0)
        self.assertEqual(rows[0]["color"], (40, 150, 60))

    def test_future_secondary_window_adds_a_row(self):
        rows = app.make_display_rows(
            {"limit_window_seconds": 604800, "used_percent": 6},
            {"limit_window_seconds": 18000, "used_percent": 20},
            "used",
        )

        self.assertEqual([row["label"] for row in rows], ["每周", "5 小时"])

    def test_free_mode_uses_remaining_percent_and_warning_color(self):
        rows = app.make_display_rows(
            {"limit_window_seconds": 604800, "used_percent": 95},
            None,
            "free",
        )

        self.assertEqual(rows[0]["percent"], 5.0)
        self.assertEqual(rows[0]["color"], (200, 40, 40))

    def test_window_without_numeric_percent_is_ignored(self):
        rows = app.make_display_rows(
            {"limit_window_seconds": 604800, "used_percent": "6"},
            None,
            "used",
        )

        self.assertEqual(rows, [])


class OverlayControllerTests(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        settings = dict(app.DEFAULT_SETTINGS)
        self.overlay = app.OverlayWindow(
            settings,
            persist=lambda name, value: self.saved.__setitem__(name, value),
        )

    def test_layout_change_updates_state_and_persists(self):
        self.overlay.set_layout("micro")

        self.assertEqual(self.overlay.layout, "micro")
        self.assertEqual(self.saved["layout"], "micro")

    def test_double_click_cycle_uses_all_layouts(self):
        self.overlay.cycle_layout()
        self.assertEqual(self.overlay.layout, "micro")
        self.overlay.cycle_layout()
        self.assertEqual(self.overlay.layout, "vertical")

    def test_passthrough_and_topmost_are_independent(self):
        self.overlay.set_click_through(True)
        self.overlay.set_topmost(False)

        self.assertTrue(self.overlay.click_through)
        self.assertFalse(self.overlay.topmost)
        self.assertTrue(self.saved["click_through"])
        self.assertFalse(self.saved["topmost"])

    def test_layout_sizes_are_stable(self):
        self.assertEqual(app.overlay_size("full", 1), (300, 110))
        self.assertEqual(app.overlay_size("full", 2), (300, 138))
        self.assertEqual(app.overlay_size("micro", 2), (245, 52))
        self.assertEqual(app.overlay_size("vertical", 2), (165, 128))


class RefreshTests(unittest.TestCase):
    def test_refresh_coordinator_rejects_overlap_until_current_refresh_ends(self):
        coordinator = app.RefreshCoordinator(lambda: None)

        self.assertTrue(coordinator.try_begin())
        self.assertFalse(coordinator.try_begin())
        coordinator.end()
        self.assertTrue(coordinator.try_begin())
        coordinator.end()


class StartupTests(unittest.TestCase):
    def test_run_value_uses_current_pythonw_sibling_when_available(self):
        current = r"C:\Python Path\python.exe"
        expected_pythonw = r"C:\Python Path\pythonw.exe"
        with patch.object(app.sys, "executable", current), patch.object(
            app.os.path, "exists", return_value=True
        ):
            value = app._run_value()

        self.assertEqual(value, f'"{expected_pythonw}" "{app._MONITOR_PATH}"')

    def test_run_value_keeps_current_executable_without_pythonw_sibling(self):
        current = r"C:\Portable\runtime.exe"
        with patch.object(app.sys, "executable", current), patch.object(
            app.os.path, "exists", return_value=False
        ):
            value = app._run_value()

        self.assertEqual(value, f'"{current}" "{app._MONITOR_PATH}"')


class AppearanceTests(unittest.TestCase):
    def test_invalid_appearance_values_fall_back_to_safe_defaults(self):
        self.assertEqual(app._validated_setting("accent_color", "purple"), "green")
        self.assertEqual(app._validated_setting("opacity", 63), 63)
        self.assertEqual(app._validated_setting("opacity", 19), 100)
        self.assertEqual(app._validated_setting("opacity", 101), 100)

    def test_palette_uses_one_color_and_preserves_warning_override(self):
        try:
            normal = app.appearance_palette("cyan", (40, 150, 60))
            warning = app.appearance_palette("cyan", (200, 40, 40))
        except TypeError as error:
            self.fail(f"unified palette API is not implemented: {error}")
        self.assertEqual(
            normal,
            ((60, 210, 255), (245, 245, 245), (205, 212, 220)),
        )
        self.assertEqual(
            warning,
            ((200, 40, 40), (245, 245, 245), (205, 212, 220)),
        )

    def test_overlay_persists_appearance_changes(self):
        saved = {}
        overlay = app.OverlayWindow(
            dict(app.DEFAULT_SETTINGS),
            persist=lambda name, value: saved.__setitem__(name, value),
        )

        overlay.set_accent_color("cyan")
        overlay.set_opacity(70)

        self.assertEqual(
            (overlay.accent_color, overlay.opacity),
            ("cyan", 70),
        )
        self.assertEqual(
            {key: saved[key] for key in ("accent_color", "opacity")},
            {
                "accent_color": "cyan",
                "opacity": 70,
            },
        )


if __name__ == "__main__":
    unittest.main()
