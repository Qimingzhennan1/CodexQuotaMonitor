# Quota Accent Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Limit the selectable color to quota percentages and filled progress bars.

**Architecture:** Make `appearance_palette` return separate accent, fixed text, and fixed muted colors. Update the three layout painters to apply the accent only to percentage values and filled progress bars.

**Tech Stack:** Python, ctypes/Win32, unittest

## Global Constraints

- Keep the existing single color menu and `accent_color` setting.
- Keep yellow and red quota warning overrides.
- Do not change opacity, layout, topmost, click-through, or tray behavior.
- Add no dependencies or source files.

---

### Task 1: Restrict the accent color

**Files:**
- Modify: `codex_quota_tray.py:227-617`
- Test: `tests/test_codex_quota_tray.py:274-289`

**Interfaces:**
- Consumes: `appearance_palette(accent, quota_color)`
- Produces: `(accent_color, text_color, muted_color)` where only `accent_color` is selectable or warning-driven

- [ ] **Step 1: Write the failing palette test**

```python
normal = app.appearance_palette("cyan", (40, 150, 60))
self.assertEqual(normal, ((60, 210, 255), (245, 245, 245), (205, 212, 220)))
```

- [ ] **Step 2: Run the focused test**

Run: `python -m unittest tests.test_codex_quota_tray.AppearanceTests -v`

Expected: FAIL because the current function returns only the accent tuple.

- [ ] **Step 3: Implement the mapping and painter changes**

Return accent, fixed white text, and fixed gray muted colors. Use accent only for percentage text and filled bars; use fixed text for titles and labels; use fixed muted color for reset/update text; use fixed gray for the micro indicator.

- [ ] **Step 4: Verify and restart**

Run `python -m py_compile codex_quota_tray.py` and `python -m unittest discover -s tests -v`, then restart only the active monitor processes and confirm the new process remains running.
