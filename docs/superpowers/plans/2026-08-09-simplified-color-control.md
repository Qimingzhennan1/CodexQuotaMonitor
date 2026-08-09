# Simplified Color Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace three overlapping color settings with one unified color control.

**Architecture:** Keep `accent_color` as the only persisted color state. Collapse palette calculation to one selected color with warning overrides, then remove the mode and text-color entries from both menus.

**Tech Stack:** Python, ctypes/Win32, pystray, unittest

## Global Constraints

- Keep green, cyan, orange, and white choices.
- Keep yellow and red warning overrides.
- Do not change opacity, layout, topmost, click-through, or tray visibility behavior.
- Add no dependencies and no new source files.

---

### Task 1: Unified palette behavior

**Files:**
- Modify: `codex_quota_tray.py:29-241`
- Test: `tests/test_codex_quota_tray.py:267-334`

**Interfaces:**
- Consumes: `COLOR_PRESETS`, `OverlayWindow.set_accent_color(value)`
- Produces: `appearance_palette(accent, quota_color)` returning one RGB tuple used by every overlay element

- [ ] **Step 1: Write the failing palette test**

```python
def test_palette_uses_one_color_and_preserves_warning_override(self):
    self.assertEqual(app.appearance_palette("cyan", (40, 150, 60)), (60, 210, 255))
    self.assertEqual(app.appearance_palette("cyan", (200, 40, 40)), (200, 40, 40))
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m unittest tests.test_codex_quota_tray.AppearanceTests -v`

Expected: FAIL because `appearance_palette` still requires mode and text arguments and returns three colors.

- [ ] **Step 3: Implement the minimal palette change**

Remove `COLOR_MODES`, `color_mode`, and `text_color` validation/controller use. Change `appearance_palette` to return the selected preset unless the quota color is yellow or red, and use that returned color for title, labels, percentage, progress bar, and reset text.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `python -m unittest tests.test_codex_quota_tray.AppearanceTests -v`

Expected: all appearance tests pass after obsolete assertions are removed or rewritten around unified behavior.

### Task 2: One color entry in each menu

**Files:**
- Modify: `codex_quota_tray.py:978-1012`
- Modify: `codex_quota_tray.py:1299-1322`

**Interfaces:**
- Consumes: `OverlayWindow.accent_color`, `OverlayWindow.set_accent_color(value)`, `next_choice(choices, current)`
- Produces: one overlay menu row `配色：当前颜色` and one tray submenu `配色`

- [ ] **Step 1: Replace the overlay menu entries**

Remove command IDs 120 and 122. Label command 121 as `配色：{当前颜色}` and cycle `COLOR_PRESETS` when selected.

- [ ] **Step 2: Replace the tray menu entries**

Remove the “配色模式”和“文字颜色” menu items. Rename “主题颜色” to “配色” and keep its four radio choices.

- [ ] **Step 3: Verify the complete program**

Run: `python -m py_compile codex_quota_tray.py` and `python -m unittest discover -s tests -v`.

Expected: syntax succeeds and every test passes.

- [ ] **Step 4: Restart and smoke-check**

Stop only the running `codex_quota_tray.py` processes, start the updated script with `pythonw.exe`, and confirm the process remains running.
