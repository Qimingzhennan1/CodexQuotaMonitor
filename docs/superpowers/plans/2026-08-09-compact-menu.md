# Compact Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce menu clutter while preserving every existing monitor control.

**Architecture:** Replace the overlay's three separate layout rows with one cycling row. Recompose the pystray menu into `外观` and `更多设置` submenus while reusing all existing callbacks and persisted settings.

**Tech Stack:** Python, ctypes/Win32 menus, pystray, unittest

## Global Constraints

- Preserve every existing setting and callback.
- Add no settings window, dependency, or registry value.
- Keep the overlay menu limited to immediate actions.
- Keep the tray menu as the complete control surface.

---

### Task 1: Compact overlay menu

**Files:**
- Modify: `codex_quota_tray.py:946-985`
- Test: `tests/test_codex_quota_tray.py`

**Interfaces:**
- Consumes: `OverlayWindow.layout`, `OverlayWindow.accent_color`, `OverlayWindow.cycle_layout()`
- Produces: `overlay_menu_labels(layout, accent_color)` and a six-row native menu including one separator

- [ ] **Step 1: Write the failing label test**

```python
def test_overlay_menu_labels_are_compact(self):
    self.assertEqual(
        app.overlay_menu_labels("vertical", "green"),
        (
            "样式: 紧凑竖版",
            "配色: 绿色",
            "调整透明度…",
            "鼠标穿透",
            "隐藏悬浮窗",
        ),
    )
```

- [ ] **Step 2: Run the focused test**

Run: `python -m unittest tests.test_codex_quota_tray.OverlayLogicTests -v`

Expected: FAIL because `overlay_menu_labels` does not exist.

- [ ] **Step 3: Implement the compact native menu**

Add the pure label function, use command 101 to call `cycle_layout()`, retain commands 121, 123, 111, and 112, and remove the three layout rows plus the topmost row.

- [ ] **Step 4: Run the focused test**

Run: `python -m unittest tests.test_codex_quota_tray.OverlayLogicTests -v`

Expected: all overlay logic tests pass.

### Task 2: Group tray controls

**Files:**
- Modify: `codex_quota_tray.py:1241-1292`

**Interfaces:**
- Consumes: existing layout, appearance, topmost, display-mode, startup, refresh, and quit callbacks
- Produces: tray top-level items for visibility, style, appearance, click-through, refresh, more settings, separator, and exit

- [ ] **Step 1: Build the `外观` submenu**

Nest the existing color radio menu and opacity slider command under `外观`.

- [ ] **Step 2: Build the `更多设置` submenu**

Nest topmost, display mode, and startup toggles under `更多设置`, leaving visibility, style, click-through, refresh, and exit at the top level.

- [ ] **Step 3: Verify and restart**

Run `python -m py_compile codex_quota_tray.py` and `python -m unittest discover -s tests -v`, restart only the active monitor processes, and smoke-check the overlay menu window procedure.
