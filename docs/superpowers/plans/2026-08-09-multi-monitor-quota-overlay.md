# Multi-Monitor Codex Quota Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, draggable, multi-monitor Codex quota overlay with three switchable layouts and optional mouse passthrough while preserving the existing tray application.

**Architecture:** Keep Windows UI integration in `codex_quota_tray.py`, but extract state transitions and geometry decisions into pure functions that can be tested without creating windows. Use one background refresh coordinator, one dedicated Win32 overlay thread, and registry-backed settings under the existing per-user application key.

**Tech Stack:** Python 3.13, ctypes/Win32, pystray, Pillow, requests, winreg, standard-library unittest.

## Global Constraints

- Keep the existing tray icon and menu capabilities.
- Do not add Qt, Electron, Rainmeter, or another GUI runtime.
- Derive quota rows from the API response; never hard-code a five-hour window.
- Support `full`, `micro`, and `vertical` overlay layouts.
- Support draggable placement on any monitor, topmost toggling, and optional mouse passthrough.
- Store settings in `HKCU\Software\CodexQuotaMonitor`.
- Failed refreshes must mark data stale; missing fields must not crash rendering.
- The workspace is not a Git repository, so each task ends with tests and a source hash/status checkpoint instead of a commit.

---

### Task 1: Quota state transitions and dynamic labels

**Files:**
- Modify: `codex_quota_tray.py:20-160`
- Create: `tests/test_codex_quota_tray.py`

**Interfaces:**
- Produces: `quota_label(win: dict | None) -> str`, `display_percent(win: dict | None, mode: str) -> float | None`, `set_fetch_error(message: str) -> None`, and safe `make_title()` behavior.
- Consumes: Existing `state`, `lock`, `fetch()`, `reset_str()`, and usage response dictionaries.

- [ ] **Step 1: Write failing state and label tests**

```python
import unittest
from unittest.mock import patch
import codex_quota_tray as app


class QuotaStateTests(unittest.TestCase):
    def setUp(self):
        with app.lock:
            app.state.update(ok=False, stale=False, error="", plan="-",
                             primary=None, secondary=None, credits=None,
                             updated=0)

    def test_weekly_window_uses_weekly_label(self):
        self.assertEqual(app.quota_label({"limit_window_seconds": 604800}), "每周")

    def test_unknown_window_uses_generic_label(self):
        self.assertEqual(app.quota_label({"limit_window_seconds": 1234}), "额度")

    def test_failed_refresh_marks_successful_data_stale(self):
        with app.lock:
            app.state.update(ok=True, stale=False, primary={"used_percent": 6}, updated=100)
        app.set_fetch_error("offline")
        with app.lock:
            self.assertFalse(app.state["ok"])
            self.assertTrue(app.state["stale"])
            self.assertEqual(app.state["updated"], 100)

    def test_title_handles_missing_primary(self):
        with app.lock:
            app.state.update(ok=True, stale=False, primary=None, error="")
        self.assertIn("暂无额度数据", app.make_title())
```

- [ ] **Step 2: Run tests and verify red state**

Run: `python.exe -m unittest tests.test_codex_quota_tray.QuotaStateTests -v`

Expected: failures for missing `stale`, `quota_label`, and `set_fetch_error`, plus the existing `None` formatting error.

- [ ] **Step 3: Implement the minimal state helpers**

```python
state = {
    "ok": False, "stale": False, "error": "", "plan": "-",
    "primary": None, "secondary": None, "credits": None, "updated": 0,
}


def quota_label(win):
    seconds = win.get("limit_window_seconds") if isinstance(win, dict) else None
    if seconds == 604800:
        return "每周"
    if seconds == 18000:
        return "5 小时"
    return "额度"


def display_percent(win, mode=None):
    if not isinstance(win, dict):
        return None
    value = win.get("used_percent")
    if not isinstance(value, (int, float)):
        return None
    value = max(0.0, min(100.0, float(value)))
    return 100.0 - value if (mode or SHOW_MODE) == "free" else value


def set_fetch_error(message):
    with lock:
        state["ok"] = False
        state["stale"] = state["primary"] is not None
        state["error"] = message
```

Call `set_fetch_error()` from every `fetch()` failure branch, clear `stale` on success, and make `make_title()` return `Codex: 暂无额度数据` when no displayable primary percentage exists.

- [ ] **Step 4: Run Task 1 tests**

Run: `python.exe -m unittest tests.test_codex_quota_tray.QuotaStateTests -v`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Record checkpoint**

Run: `Get-FileHash codex_quota_tray.py,tests/test_codex_quota_tray.py -Algorithm SHA256`

Expected: both files exist and produce hashes.

### Task 2: Persisted overlay settings and monitor-safe geometry

**Files:**
- Modify: `codex_quota_tray.py`
- Modify: `tests/test_codex_quota_tray.py`

**Interfaces:**
- Produces: `LAYOUTS`, `next_layout(layout: str) -> str`, `clamp_overlay_position(x, y, width, height, work_areas) -> tuple[int, int]`, `load_settings() -> dict`, and `save_setting(name, value) -> None`.
- Consumes: `winreg`, primary-screen metrics, and monitor work-area rectangles supplied by the overlay layer.

- [ ] **Step 1: Add failing layout and geometry tests**

```python
class OverlayLogicTests(unittest.TestCase):
    def test_layout_cycle(self):
        self.assertEqual(app.next_layout("full"), "micro")
        self.assertEqual(app.next_layout("micro"), "vertical")
        self.assertEqual(app.next_layout("vertical"), "full")

    def test_visible_saved_position_is_preserved(self):
        areas = [(0, 0, 1920, 1040), (1920, 0, 3200, 720)]
        self.assertEqual(app.clamp_overlay_position(2100, 20, 300, 100, areas), (2100, 20))

    def test_offscreen_position_falls_back_to_primary_top_left(self):
        areas = [(0, 0, 1920, 1040)]
        self.assertEqual(app.clamp_overlay_position(4000, 50, 300, 100, areas), (12, 12))
```

- [ ] **Step 2: Run new tests and verify they fail**

Run: `python.exe -m unittest tests.test_codex_quota_tray.OverlayLogicTests -v`

Expected: missing-function failures.

- [ ] **Step 3: Implement layout, defaults, registry settings, and geometry**

```python
LAYOUTS = ("full", "micro", "vertical")
DEFAULT_SETTINGS = {
    "layout": "full", "x": 12, "y": 12, "topmost": True,
    "click_through": False, "overlay_visible": True, "show_mode": "used",
}


def next_layout(layout):
    try:
        return LAYOUTS[(LAYOUTS.index(layout) + 1) % len(LAYOUTS)]
    except ValueError:
        return LAYOUTS[0]


def clamp_overlay_position(x, y, width, height, work_areas):
    for left, top, right, bottom in work_areas:
        if x < right and x + width > left and y < bottom and y + height > top:
            return int(x), int(y)
    if work_areas:
        left, top, _, _ = work_areas[0]
        return left + 12, top + 12
    return 12, 12
```

Use registry value types `REG_SZ` for `layout`/`show_mode` and `REG_DWORD` for coordinates and booleans. Invalid values fall back to `DEFAULT_SETTINGS`.

- [ ] **Step 4: Run Task 2 tests**

Run: `python.exe -m unittest tests.test_codex_quota_tray.OverlayLogicTests -v`

Expected: all Task 2 tests pass without writing the registry from tests.

- [ ] **Step 5: Record checkpoint**

Run: `python.exe -m unittest discover -s tests -v`

Expected: all tests pass.

### Task 3: Win32 overlay window and three renderers

**Files:**
- Modify: `codex_quota_tray.py:163-321`
- Modify: `tests/test_codex_quota_tray.py`

**Interfaces:**
- Produces: `OverlayWindow.start()`, `.show()`, `.hide()`, `.set_layout()`, `.set_topmost()`, `.set_click_through()`, `.invalidate()`, and `.stop()`.
- Consumes: quota state snapshot, settings helpers, `make_display_rows()`, Win32 window messages, and tray callbacks.

- [ ] **Step 1: Add failing display-row tests**

```python
class DisplayRowTests(unittest.TestCase):
    def test_single_weekly_window_builds_one_row(self):
        rows = app.make_display_rows(
            {"limit_window_seconds": 604800, "used_percent": 6,
             "reset_after_seconds": 600000}, None, "used")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "每周")
        self.assertEqual(rows[0]["percent"], 6.0)

    def test_future_secondary_window_adds_a_row(self):
        rows = app.make_display_rows(
            {"limit_window_seconds": 604800, "used_percent": 6},
            {"limit_window_seconds": 18000, "used_percent": 20}, "used")
        self.assertEqual([row["label"] for row in rows], ["每周", "5 小时"])
```

- [ ] **Step 2: Run display-row tests and verify they fail**

Run: `python.exe -m unittest tests.test_codex_quota_tray.DisplayRowTests -v`

Expected: missing `make_display_rows` failure.

- [ ] **Step 3: Implement rows and `OverlayWindow`**

Implement `make_display_rows()` as a pure function returning dictionaries with `label`, `percent`, `reset`, and `color`. Replace the one-shot detail popup globals with a dedicated overlay thread and command queue. Handle these messages:

```python
WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_DISPLAYCHANGE = 0x007E
WM_DPICHANGED = 0x02E0
```

Create the window class with `CS_DBLCLKS`, render sizes `full=(300, 104 or dynamic)`, `micro=(245, 48)`, and `vertical=(158, 118)`, and update extended styles with:

```python
styles = WS_EX_TOOLWINDOW
if topmost:
    styles |= WS_EX_TOPMOST
if click_through:
    styles |= WS_EX_TRANSPARENT | WS_EX_LAYERED
```

During painting, retain the previous selected font, select each temporary font, restore the previous object, then call `DeleteObject` for every created font. Clamp percentage bar widths to `0..width`.

- [ ] **Step 4: Run Task 3 tests and syntax compilation**

Run: `python.exe -m unittest tests.test_codex_quota_tray.DisplayRowTests -v`

Expected: all display-row tests pass.

Run: `python.exe -m py_compile codex_quota_tray.py`

Expected: exit code 0.

- [ ] **Step 5: Record checkpoint**

Run: `python.exe -m unittest discover -s tests -v`

Expected: all tests pass.

### Task 4: Tray integration and non-blocking refresh

**Files:**
- Modify: `codex_quota_tray.py:323-477`
- Modify: `tests/test_codex_quota_tray.py`

**Interfaces:**
- Consumes: `OverlayWindow`, settings helpers, `fetch()`.
- Produces: tray submenus for visibility, layout, topmost, passthrough, display mode, and a non-blocking `request_refresh()`.

- [ ] **Step 1: Add a failing refresh serialization test**

```python
class RefreshTests(unittest.TestCase):
    def test_refresh_coordinator_rejects_overlap(self):
        coordinator = app.RefreshCoordinator(lambda: None)
        self.assertTrue(coordinator.try_begin())
        self.assertFalse(coordinator.try_begin())
        coordinator.end()
        self.assertTrue(coordinator.try_begin())
```

- [ ] **Step 2: Run the refresh test and verify it fails**

Run: `python.exe -m unittest tests.test_codex_quota_tray.RefreshTests -v`

Expected: missing `RefreshCoordinator` failure.

- [ ] **Step 3: Implement refresh coordination and tray commands**

```python
class RefreshCoordinator:
    def __init__(self, callback):
        self.callback = callback
        self._lock = threading.Lock()

    def try_begin(self):
        return self._lock.acquire(blocking=False)

    def end(self):
        if self._lock.locked():
            self._lock.release()
```

Run manual refresh in a daemon thread. Remove the duplicate immediate request by keeping the initial synchronous `fetch()` and having `refresh_loop()` wait `REFRESH_INTERVAL` before its first scheduled request. After each completed fetch, update tray icon/title and call `overlay.invalidate()`.

Add tray items for:

```text
悬浮窗: 显示/隐藏
悬浮样式 > 完整横版 / 极简横条 / 紧凑竖版
始终置顶: 开/关
鼠标穿透: 开/关
显示口径: 已用/可用
刷新
开机启动
退出
```

When passthrough is enabled, retain the tray as the guaranteed control path for disabling it.

- [ ] **Step 4: Run Task 4 and full tests**

Run: `python.exe -m unittest tests.test_codex_quota_tray.RefreshTests -v`

Expected: refresh serialization test passes.

Run: `python.exe -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 5: Record checkpoint**

Run: `python.exe -m pip check`

Expected: `No broken requirements found.`

### Task 5: Startup portability and Windows smoke verification

**Files:**
- Modify: `codex_quota_tray.py:404-461`
- Modify: `tests/test_codex_quota_tray.py`
- Modify: `docs/superpowers/specs/2026-08-09-multi-monitor-quota-overlay-design.md` only if implementation constraints require an explicitly documented adjustment.

**Interfaces:**
- Consumes: `sys.executable`, overlay lifecycle, tray lifecycle.
- Produces: portable `_run_value()`, exact startup-registry validation, and a clean shutdown path.

- [ ] **Step 1: Add failing startup command tests**

```python
class StartupTests(unittest.TestCase):
    def test_run_value_quotes_current_python_and_script(self):
        with patch.object(app.sys, "executable", r"C:\Python Path\pythonw.exe"):
            value = app._run_value()
        self.assertIn('"C:\\Python Path\\pythonw.exe"', value)
        self.assertIn('"' + app._MONITOR_PATH + '"', value)
```

- [ ] **Step 2: Run startup test and verify it fails against the hard-coded interpreter**

Run: `python.exe -m unittest tests.test_codex_quota_tray.StartupTests -v`

Expected: assertion failure because `_run_value()` does not use `sys.executable`.

- [ ] **Step 3: Use the current interpreter and implement clean shutdown**

Import `sys`, derive the launch executable from `sys.executable`, converting `python.exe` to sibling `pythonw.exe` only when that sibling exists. Make `startup_enabled()` compare the stored registry command with `_run_value()` rather than checking only value existence. On exit, signal the refresh loop, stop the overlay thread, release the single-instance socket, and stop the tray.

- [ ] **Step 4: Run full automated verification**

Run: `python.exe -m unittest discover -s tests -v`

Expected: all tests pass.

Run: `python.exe -m py_compile codex_quota_tray.py tests/test_codex_quota_tray.py`

Expected: exit code 0.

Run: `python.exe -m pip check`

Expected: `No broken requirements found.`

- [ ] **Step 5: Run Windows smoke verification**

Launch the program with its configured `pythonw.exe`, confirm one tray icon and one overlay appear, then verify: drag to another monitor, restart and confirm restored position, cycle all layouts, enable passthrough and disable it from the tray, toggle topmost, disconnect/reconnect the portable display, manually refresh, and exit. Confirm the process terminates and no duplicate instance remains.

- [ ] **Step 6: Final diff/checkpoint**

Run: `Get-FileHash codex_quota_tray.py,tests/test_codex_quota_tray.py,docs/superpowers/specs/2026-08-09-multi-monitor-quota-overlay-design.md -Algorithm SHA256`

Expected: all implementation and documentation files exist and produce hashes.
