# Corner Snap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Snap the draggable overlay to a monitor corner only when released within 20 px of that corner.

**Architecture:** Add a pure geometry function that selects the monitor with the largest window overlap and evaluates its four work-area corners. Call it from the existing `WM_EXITSIZEMOVE` persistence path, move the window only when a corner matches, then persist the final coordinates.

**Tech Stack:** Python, ctypes/Win32, unittest

## Global Constraints

- Preserve arbitrary free placement outside corner thresholds.
- Snap only when both axes are within 20 px of the same corner.
- Use monitor work areas so the taskbar is not covered.
- Add no menu item, setting, animation, dependency, or registry field.

---

### Task 1: Corner geometry

**Files:**
- Modify: `codex_quota_tray.py:111-121`
- Test: `tests/test_codex_quota_tray.py`

**Interfaces:**
- Produces: `snap_overlay_to_corner(x, y, width, height, work_areas, threshold=20) -> tuple[int, int]`
- Consumes: monitor work areas expressed as `(left, top, right, bottom)` tuples

- [ ] **Step 1: Write failing geometry tests**

```python
def test_overlay_snaps_to_each_corner_within_threshold(self):
    area = [(0, 0, 1920, 1040)]
    self.assertEqual(app.snap_overlay_to_corner(12, 8, 300, 100, area), (0, 0))
    self.assertEqual(app.snap_overlay_to_corner(1608, 8, 300, 100, area), (1620, 0))
    self.assertEqual(app.snap_overlay_to_corner(12, 932, 300, 100, area), (0, 940))
    self.assertEqual(app.snap_overlay_to_corner(1608, 932, 300, 100, area), (1620, 940))

def test_overlay_does_not_snap_to_a_single_edge(self):
    self.assertEqual(
        app.snap_overlay_to_corner(8, 400, 300, 100, [(0, 0, 1920, 1040)]),
        (8, 400),
    )
```

- [ ] **Step 2: Run the focused tests**

Run: `python -m unittest tests.test_codex_quota_tray.OverlayLogicTests -v`

Expected: FAIL because `snap_overlay_to_corner` does not exist.

- [ ] **Step 3: Implement the pure geometry function**

Compute positive intersection area with every work area, choose the largest, build the four exact corner positions, and return the nearest candidate only when both axis distances are at most `threshold`; otherwise return the original integer coordinates.

- [ ] **Step 4: Run the focused tests**

Run: `python -m unittest tests.test_codex_quota_tray.OverlayLogicTests -v`

Expected: all overlay logic tests pass.

### Task 2: Drag-end integration

**Files:**
- Modify: `codex_quota_tray.py:911-918`

**Interfaces:**
- Consumes: `snap_overlay_to_corner`, `_monitor_work_areas`, `GetWindowRect`, `SetWindowPos`
- Produces: snapped and persisted `OverlayWindow.x` / `OverlayWindow.y`

- [ ] **Step 1: Integrate snapping into position persistence**

Read the current rectangle, call the geometry function with its dimensions, reposition with `SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE` only when coordinates change, then persist the final coordinates.

- [ ] **Step 2: Verify, restart, and publish**

Run `python -m py_compile codex_quota_tray.py` and `python -m unittest discover -s tests -v`, restart only active monitor processes, commit the plan/code/tests, and push `main` through the configured local proxy.
