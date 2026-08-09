# Overlay Appearance Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three switchable color modes, four preset colors, and four opacity levels to the existing quota overlay.

**Architecture:** Extend the existing registry-backed settings and `OverlayWindow` controller. Keep drawing in the current Win32 paint path, derive a small palette before rendering, and reuse generic tray callbacks to avoid duplicating menu logic.

**Tech Stack:** Python 3.13, ctypes/Win32, pystray, winreg, unittest.

## Global Constraints

- Do not add a color picker, window, dependency, or new runtime module.
- Presets are green, cyan, orange, and white.
- Opacity choices are 50, 70, 85, and 100 percent.
- Warning red/yellow overrides the selected accent color.
- Settings apply immediately and persist under `HKCU\Software\CodexQuotaMonitor`.
- Keep tests limited to the new setting and palette behavior.

---

### Task 1: Appearance settings and palette

**Files:**
- Modify: `codex_quota_tray.py`
- Modify: `tests/test_codex_quota_tray.py`

**Interfaces:**
- Produces: `COLOR_MODES`, `COLOR_PRESETS`, `OPACITY_LEVELS`, `appearance_palette(mode, accent, text, quota_color)`.
- Consumes: existing `DEFAULT_SETTINGS`, `_validated_setting()`, and registry load/save functions.

- [ ] Write failing tests that invalid values fall back safely and each color mode returns the expected accent/text pair.

```python
def test_highlight_palette_uses_accent_and_white_text(self):
    accent, text, muted = app.appearance_palette("highlight", "cyan", "orange", app.GREEN[:3])
    self.assertEqual(accent, app.COLOR_PRESETS["cyan"])
    self.assertEqual(text, app.COLOR_PRESETS["white"])
```

- [ ] Run the new test class and confirm missing appearance settings/palette failures.
- [ ] Add defaults `color_mode="highlight"`, `accent_color="green"`, `text_color="white"`, and `opacity=100`; validate against the fixed tuples.
- [ ] Implement `appearance_palette()` so warning red/yellow remains unchanged while normal green is replaced by the chosen accent.

```python
def appearance_palette(mode, accent, text, quota_color):
    chosen_accent = COLOR_PRESETS[accent]
    if quota_color in (RED[:3], YELLOW[:3]):
        chosen_accent = quota_color
    chosen_text = chosen_accent if mode == "theme" else COLOR_PRESETS["white"]
    if mode == "split":
        chosen_text = COLOR_PRESETS[text]
    return chosen_accent, chosen_text, chosen_text
```

- [ ] Run the new test class and confirm it passes.

### Task 2: Apply appearance to the live overlay

**Files:**
- Modify: `codex_quota_tray.py`
- Modify: `tests/test_codex_quota_tray.py`

**Interfaces:**
- Produces: `OverlayWindow.set_color_mode()`, `.set_accent_color()`, `.set_text_color()`, `.set_opacity()`.
- Consumes: Task 1 settings and palette.

- [ ] Write one failing controller test that changes and persists all four appearance fields.
- [ ] Run the controller test and confirm the setters are missing.
- [ ] Add the four controller properties/setters and trigger the existing overlay update message.

```python
def set_opacity(self, value):
    self.opacity = _validated_setting("opacity", value)
    self._persist("opacity", self.opacity)
    self._notify_changed()
```

- [ ] Replace hard-coded normal text colors in `_paint_overlay()` with the palette values.
- [ ] Apply alpha with `SetLayeredWindowAttributes(... round(opacity * 255 / 100), ...)` during creation and updates.
- [ ] Run the controller test and syntax compilation.

### Task 3: Tray and overlay menus

**Files:**
- Modify: `codex_quota_tray.py`

**Interfaces:**
- Produces: tray radio submenus for color mode, accent, text, and opacity; overlay right-click cycle commands for the same settings.
- Consumes: Task 2 controller setters.

- [ ] Add generic tray selection callbacks and checked predicates.

```python
def select_appearance(name, value):
    def callback(icon_obj, item):
        getattr(overlay, f"set_{name}")(value)
        icon_obj.update_menu()
    return callback
```
- [ ] Add four compact tray submenus.
- [ ] Add four right-click commands that cycle color mode, accent, text, and opacity to keep the native menu small.
- [ ] Restart the running app and smoke-check immediate color and alpha changes.
- [ ] Run existing tests and Python syntax compilation once.
