# Text Color and Opacity Slider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make text color changes immediately visible and replace fixed opacity presets with a live slider.

**Architecture:** Keep appearance state in `OverlayWindow`. Reuse its update/persistence path, and create a small native Win32 trackbar popup on the existing overlay UI thread.

**Tech Stack:** Python, ctypes/Win32, unittest, pystray

## Global Constraints

- Keep the tray icon and all three appearance modes.
- Keep the implementation dependency-free and small.
- Opacity range is 20–100 percent.

---

### Task 1: Appearance behavior

**Files:**
- Modify: `codex_quota_tray.py`
- Test: `tests/test_codex_quota_tray.py`

**Interfaces:**
- Consumes: `OverlayWindow.set_text_color(value)`, `_validated_setting(name, value)`
- Produces: text color auto-selects `split`; opacity accepts every integer from 20 through 100

- [ ] Write focused failing tests for the two behaviors.
- [ ] Run those tests and confirm expected failures.
- [ ] Implement the minimal controller and validation changes.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Native opacity slider

**Files:**
- Modify: `codex_quota_tray.py`

**Interfaces:**
- Consumes: `OverlayWindow.set_opacity(value)`
- Produces: `OverlayWindow.show_opacity_slider()` and a Win32 trackbar popup

- [ ] Add the popup message, native control constants, window procedure, and popup creation/cleanup.
- [ ] Replace both fixed-opacity menus with “调整透明度…”.
- [ ] Run the complete test suite and Python syntax check.
- [ ] Restart the monitor and confirm the process remains running.
