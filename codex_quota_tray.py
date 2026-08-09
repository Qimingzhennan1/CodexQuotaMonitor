#!/usr/bin/env python3
# Codex 额度系统托盘监视器（方案 B：系统托盘 + 悬浮窗）
# 运行期间不写任何磁盘文件，纯内存状态 + 网络读取 ~/.codex/auth.json（只读）
import os, sys, json, time, threading, ctypes, winreg
from ctypes import wintypes
import requests
from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import Icon, Menu, MenuItem

AUTH_PATH = os.path.expanduser("~/.codex/auth.json")
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
REFRESH_INTERVAL = 30  # 秒
FONT_PATHS = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/msgothic.ttc",
]

state = {
    "ok": False, "stale": False, "error": "", "plan": "-",
    "primary": None, "secondary": None, "credits": None,
    "updated": 0,
}
lock = threading.Lock()
icon = None  # 由 main() 设置
SHOW_MODE = "used"  # "used" = 已用额度；"free" = 可用额度(100-已用)
LAYOUTS = ("full", "micro", "vertical")
COLOR_PRESETS = {
    "green": (80, 230, 120),
    "cyan": (60, 210, 255),
    "orange": (255, 165, 50),
    "white": (245, 245, 245),
}
OPACITY_MIN = 20
OPACITY_MAX = 100
DEFAULT_SETTINGS = {
    "layout": "full",
    "x": 12,
    "y": 12,
    "topmost": True,
    "click_through": False,
    "overlay_visible": True,
    "show_mode": "used",
    "accent_color": "green",
    "opacity": 100,
}
_SETTINGS_KEY = r"Software\CodexQuotaMonitor"


def _validated_setting(name, value):
    default = DEFAULT_SETTINGS[name]
    try:
        if name == "layout":
            return value if value in LAYOUTS else default
        if name == "show_mode":
            return value if value in ("used", "free") else default
        if name == "accent_color":
            return value if value in COLOR_PRESETS else default
        if name == "opacity":
            numeric = int(value)
            return numeric if OPACITY_MIN <= numeric <= OPACITY_MAX else default
        if name in ("x", "y"):
            return int(value)
        if isinstance(default, bool):
            numeric = int(value)
            return bool(numeric) if numeric in (0, 1) else default
    except (TypeError, ValueError):
        return default
    return default


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SETTINGS_KEY) as key:
            for name in DEFAULT_SETTINGS:
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                settings[name] = _validated_setting(name, value)
    except OSError:
        pass
    return settings


def save_setting(name, value):
    if name not in DEFAULT_SETTINGS:
        raise KeyError(name)
    value = _validated_setting(name, value)
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, _SETTINGS_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        if name in (
            "layout", "show_mode", "accent_color",
            "x", "y",
        ):
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
        else:
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))


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
        return int(left) + 12, int(top) + 12
    return 12, 12


def get_font(size):
    for fp in FONT_PATHS:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def load_token():
    try:
        with open(AUTH_PATH, encoding="utf-8") as auth_file:
            d = json.load(auth_file)
        return d.get("tokens", {}).get("access_token")
    except Exception:
        return None


def set_fetch_error(message):
    with lock:
        state["ok"] = False
        state["stale"] = state.get("primary") is not None
        state["error"] = str(message)


def fetch():
    def fail(message):
        set_fetch_error(message)
        return False, message

    at = load_token()
    if not at:
        return fail("无 access_token（请先 codex login）")
    hdr = {"Authorization": f"Bearer {at}", "Content-Type": "application/json"}
    try:
        r = requests.get(USAGE_URL, headers=hdr, timeout=20)
    except Exception as e:
        return fail(f"网络错误: {e}")
    if r.status_code == 401:
        return fail("token 失效，请重新 codex login")
    if r.status_code != 200:
        return fail(f"HTTP {r.status_code}")
    try:
        j = r.json()
    except Exception:
        return fail("返回非 JSON")
    rl = j.get("rate_limit", {}) or {}
    with lock:
        state["ok"] = True
        state["stale"] = False
        state["error"] = ""
        state["plan"] = j.get("plan_type", "-")
        state["primary"] = rl.get("primary_window")
        state["secondary"] = rl.get("secondary_window")
        state["credits"] = j.get("credits")
        state["updated"] = time.time()
    return True, ""


def pct(win):
    return display_percent(win, "used")


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


def reset_str(win):
    if not win:
        return "-"
    secs = win.get("reset_after_seconds")
    if secs is None and win.get("reset_at"):
        secs = max(0, win.get("reset_at") - time.time())
    if secs is None:
        return "-"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, _ = divmod(rem, 60)
    if h >= 24:
        d, h2 = divmod(h, 24)
        return f"{d}天{h2}时"
    return f"{h}时{m}分"


# ---------- 托盘图标 ----------
RED = (200, 40, 40, 255)
YELLOW = (200, 150, 30, 255)
GREEN = (40, 150, 60, 255)


def appearance_palette(accent, quota_color):
    accent_value = COLOR_PRESETS.get(accent, COLOR_PRESETS["green"])
    if quota_color in (RED[:3], YELLOW[:3]):
        accent_value = quota_color
    return accent_value, COLOR_PRESETS["white"], (205, 212, 220)


def make_display_rows(primary, secondary, mode=None):
    mode = mode or SHOW_MODE
    rows = []
    for win in (primary, secondary):
        percent = display_percent(win, mode)
        if percent is None:
            continue
        if mode == "used":
            color = RED if percent >= 90 else (YELLOW if percent >= 70 else GREEN)
        else:
            color = RED if percent <= 10 else (YELLOW if percent <= 30 else GREEN)
        rows.append(
            {
                "label": quota_label(win),
                "percent": percent,
                "reset": reset_str(win),
                "color": color[:3],
            }
        )
    return rows


def shown_and_color(win):
    """返回 (显示百分比, 背景色)。颜色语义随模式：已用越高越红 / 可用越少越红。"""
    p = pct(win)
    if p is None:
        return None, None
    if SHOW_MODE == "used":
        disp = p
        if p >= 90:
            c = RED
        elif p >= 70:
            c = YELLOW
        else:
            c = GREEN
    else:  # free：100 - 已用，剩余越少越危险
        disp = 100 - p
        if disp <= 10:
            c = RED
        elif disp <= 30:
            c = YELLOW
        else:
            c = GREEN
    return disp, c


def make_icon():
    with lock:
        ok = state["ok"]
        win = state["primary"]
    disp, c = shown_and_color(win) if win else (None, None)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if not ok:
        bg, fg, txt = (60, 60, 60, 255), (220, 220, 220, 255), "!"
    elif disp is None:
        bg, fg, txt = (40, 40, 40, 255), (230, 230, 230, 255), "?"
    else:
        bg, fg, txt = c, (255, 255, 255, 255), f"{disp:.0f}"
    draw.ellipse([4, 4, 60, 60], fill=bg)
    f = get_font(30)
    bbox = draw.textbbox((0, 0), txt, font=f)
    w = bbox[2] - bbox[0]; h = bbox[3] - bbox[1]
    draw.text(((64 - w) / 2 - bbox[0], (64 - h) / 2 - bbox[1]), txt, font=f, fill=fg)
    if txt not in ("!", "?"):
        fp = get_font(14)
        draw.text((45, 41), "%", font=fp, fill=fg)
    return img


def make_title():
    with lock:
        ok = state["ok"]; err = state["error"]
        stale = state.get("stale", False)
        win = state["primary"]; plan = state["plan"]
    disp, _ = shown_and_color(win) if win else (None, None)
    if disp is None:
        if not ok and err:
            return f"Codex: {err[:40]}"
        return f"Codex {plan}: 暂无额度数据"
    if not ok and not stale:
        return f"Codex: {err[:40]}"
    label = "可用" if SHOW_MODE == "free" else ""
    suffix = " · 数据已过期" if stale else f" · 重置 {reset_str(win)}"
    return f"Codex {plan} {label}{disp:.0f}%{suffix}"


def overlay_size(layout, row_count):
    if layout == "micro":
        return 245, 52
    if layout == "vertical":
        return 165, 128
    return 300, 82 + max(1, int(row_count)) * 28


class OverlayWindow:
    def __init__(self, settings, persist=save_setting):
        self.layout = _validated_setting("layout", settings.get("layout"))
        self.x = _validated_setting("x", settings.get("x"))
        self.y = _validated_setting("y", settings.get("y"))
        self.topmost = _validated_setting("topmost", settings.get("topmost"))
        self.click_through = _validated_setting(
            "click_through", settings.get("click_through")
        )
        self.visible = _validated_setting(
            "overlay_visible", settings.get("overlay_visible")
        )
        self.accent_color = _validated_setting(
            "accent_color", settings.get("accent_color")
        )
        self.opacity = _validated_setting("opacity", settings.get("opacity"))
        self._persist = persist
        self.hwnd = None
        self.opacity_popup_hwnd = None
        self.opacity_slider_hwnd = None
        self.startup_error = ""

    def _notify_changed(self):
        if self.hwnd:
            _u.PostMessageW(self.hwnd, WM_APP_OVERLAY_UPDATE, 0, 0)

    def set_layout(self, layout):
        layout = _validated_setting("layout", layout)
        if layout == self.layout:
            return
        self.layout = layout
        self._persist("layout", layout)
        self._notify_changed()

    def cycle_layout(self):
        self.set_layout(next_layout(self.layout))

    def set_topmost(self, enabled):
        self.topmost = bool(enabled)
        self._persist("topmost", self.topmost)
        self._notify_changed()

    def set_click_through(self, enabled):
        self.click_through = bool(enabled)
        self._persist("click_through", self.click_through)
        self._notify_changed()

    def _set_appearance(self, name, value):
        value = _validated_setting(name, value)
        setattr(self, name, value)
        self._persist(name, value)
        self._notify_changed()

    def set_accent_color(self, value):
        self._set_appearance("accent_color", value)

    def set_opacity(self, value):
        self._set_appearance("opacity", value)


# ---------- Win32 悬浮窗（零依赖，ctypes） ----------
_u = ctypes.windll.user32
_g = ctypes.windll.gdi32
_k = ctypes.windll.kernel32
_c = ctypes.windll.comctl32

WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
GWL_EXSTYLE = -20
CS_DBLCLKS = 0x0008
WM_DESTROY = 0x0002
WM_ACTIVATE = 0x0006
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_ERASEBKGND = 0x0014
WM_HSCROLL = 0x0114
WM_NCHITTEST = 0x0084
WM_NCLBUTTONDBLCLK = 0x00A3
WM_NCRBUTTONUP = 0x00A5
WM_EXITSIZEMOVE = 0x0232
WM_DISPLAYCHANGE = 0x007E
WM_DPICHANGED = 0x02E0
WM_APP_OVERLAY_UPDATE = 0x8001
WM_APP_OVERLAY_SHOW = 0x8002
WM_APP_OVERLAY_HIDE = 0x8003
WM_APP_OVERLAY_OPACITY = 0x8004
HTCAPTION = 2
IDC_ARROW = 32512
TRANSPARENT = 1
LWA_ALPHA = 0x00000002
SW_HIDE = 0
SW_SHOW = 5
SW_SHOWNA = 8
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
MONITORINFOF_PRIMARY = 0x0001
ICC_BAR_CLASSES = 0x00000004
TBS_AUTOTICKS = 0x0001
TBM_GETPOS = 0x0400
TBM_SETPOS = 0x0405
TBM_SETRANGE = 0x0406
TBM_SETTICFREQ = 0x0414
TB_ENDTRACK = 8
WA_INACTIVE = 0
TRACKBAR_CLASS = "msctls_trackbar32"

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    LPARAM,
)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class INITCOMMONCONTROLSEX(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("dwICC", wintypes.DWORD)]


def _rgb(r, g, b):
    return int(r) | (int(g) << 8) | (int(b) << 16)


def _monitor_work_areas():
    areas = []

    def collect(hmonitor, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if _u.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rect = info.rcWork
            item = (rect.left, rect.top, rect.right, rect.bottom)
            areas.append((0 if info.dwFlags & MONITORINFOF_PRIMARY else 1, item))
        return True

    callback = MONITORENUMPROC(collect)
    _u.EnumDisplayMonitors(None, None, callback, 0)
    return [item for _, item in sorted(areas, key=lambda entry: entry[0])]


def _fill_rect(hdc, left, top, right, bottom, color):
    rect = wintypes.RECT(int(left), int(top), int(right), int(bottom))
    brush = _g.CreateSolidBrush(_rgb(*color))
    try:
        _u.FillRect(hdc, ctypes.byref(rect), brush)
    finally:
        _g.DeleteObject(brush)


def _draw_text(hdc, text, x, y, size, weight=400, color=(235, 235, 235)):
    text = str(text)
    font = _g.CreateFontW(
        -int(size), 0, 0, 0, int(weight), 0, 0, 0, 0, 0, 0, 0, 0,
        "Microsoft YaHei",
    )
    previous = _g.SelectObject(hdc, font)
    try:
        _g.SetTextColor(hdc, _rgb(*color))
        _g.TextOutW(hdc, int(x), int(y), text, len(text))
    finally:
        _g.SelectObject(hdc, previous)
        _g.DeleteObject(font)


def _quota_snapshot():
    with lock:
        return {
            "ok": state["ok"],
            "stale": state.get("stale", False),
            "error": state["error"],
            "plan": state["plan"],
            "primary": dict(state["primary"]) if state["primary"] else None,
            "secondary": dict(state["secondary"]) if state["secondary"] else None,
            "updated": state["updated"],
        }


def _paint_overlay(overlay_obj, hwnd, hdc):
    snapshot = _quota_snapshot()
    rows = make_display_rows(snapshot["primary"], snapshot["secondary"], SHOW_MODE)
    row_colors = [row["color"] for row in rows]
    quota_color = RED[:3] if RED[:3] in row_colors else (
        YELLOW[:3] if YELLOW[:3] in row_colors else GREEN[:3]
    )
    accent_color, text_color, muted_color = appearance_palette(
        overlay_obj.accent_color, quota_color
    )
    rect = wintypes.RECT()
    _u.GetClientRect(hwnd, ctypes.byref(rect))
    _fill_rect(hdc, 0, 0, rect.right, rect.bottom, (8, 10, 14))
    _g.SetBkMode(hdc, TRANSPARENT)

    if not rows:
        _draw_text(hdc, "CODEX QUOTA", 12, 10, 12, 700, text_color)
        message = snapshot["error"] or "暂无额度数据"
        _draw_text(hdc, message[:28], 12, 35, 13, 400, (225, 105, 95))
        return

    primary = rows[0]
    stale = snapshot["stale"]
    plan = str(snapshot["plan"] or "-").upper()
    mode_label = "可用" if SHOW_MODE == "free" else "已用"

    if overlay_obj.layout == "micro":
        _fill_rect(hdc, 11, 21, 19, 29, muted_color)
        _draw_text(hdc, f"Codex {primary['label']}", 27, 14, 13, 400, text_color)
        _draw_text(hdc, f"{primary['percent']:.0f}%", 155, 8, 24, 700, accent_color)
        if stale:
            _draw_text(hdc, "旧", 221, 17, 10, 700, (220, 160, 55))
        return

    if overlay_obj.layout == "vertical":
        _draw_text(hdc, f"CODEX · {plan}", 12, 9, 11, 700, text_color)
        _draw_text(hdc, f"{primary['label']}{mode_label}", 12, 31, 12, 400, text_color)
        _draw_text(hdc, f"{primary['percent']:.0f}%", 12, 49, 32, 700, accent_color)
        _fill_rect(hdc, 12, 87, 151, 90, (45, 52, 62))
        _fill_rect(hdc, 12, 87, 12 + int(139 * primary["percent"] / 100), 90, accent_color)
        _draw_text(hdc, f"重置 {primary['reset']}", 12, 97, 11, 400, muted_color)
        if stale:
            _draw_text(hdc, "数据已过期", 91, 10, 10, 700, (220, 160, 55))
        return

    _draw_text(hdc, f"CODEX QUOTA · {plan}", 13, 9, 11, 700, text_color)
    if stale:
        _draw_text(hdc, "数据已过期", 220, 9, 10, 700, (220, 160, 55))
    y = 34
    for row in rows:
        _draw_text(hdc, row["label"], 13, y, 13, 400, text_color)
        _draw_text(hdc, f"{row['percent']:.0f}%", 70, y - 1, 16, 700, accent_color)
        _fill_rect(hdc, 115, y + 8, 224, y + 11, (45, 52, 62))
        fill_right = 115 + int(109 * row["percent"] / 100)
        _fill_rect(hdc, 115, y + 8, fill_right, y + 11, accent_color)
        _draw_text(hdc, row["reset"], 235, y + 1, 10, 400, muted_color)
        y += 28
    updated = snapshot["updated"]
    updated_text = time.strftime("%H:%M:%S", time.localtime(updated)) if updated else "-"
    _draw_text(hdc, f"{mode_label} · {updated_text} 更新", 13, y + 4, 10, 400, muted_color)


overlay = None


def _opacity_popup_wndproc(hwnd, msg, wp, lp):
    current = overlay
    if current is None:
        return _u.DefWindowProcW(hwnd, msg, wp, lp)
    if msg == WM_HSCROLL and current.opacity_slider_hwnd:
        value = int(_u.SendMessageW(current.opacity_slider_hwnd, TBM_GETPOS, 0, 0))
        current.opacity = value
        current._notify_changed()
        _u.SetWindowTextW(hwnd, f"透明度: {value}%")
        if int(wp) & 0xFFFF == TB_ENDTRACK:
            current.set_opacity(value)
        return 0
    if msg == WM_ACTIVATE and (int(wp) & 0xFFFF) == WA_INACTIVE:
        current.set_opacity(current.opacity)
        _u.DestroyWindow(hwnd)
        return 0
    if msg == WM_CLOSE:
        current.set_opacity(current.opacity)
        _u.DestroyWindow(hwnd)
        return 0
    if msg == WM_DESTROY:
        current.opacity_popup_hwnd = None
        current.opacity_slider_hwnd = None
        return 0
    return _u.DefWindowProcW(hwnd, msg, wp, lp)


_OPACITY_POPUP_WNDPROC = WNDPROC(_opacity_popup_wndproc)


def _show_opacity_popup(current):
    if current.opacity_popup_hwnd and _u.IsWindow(current.opacity_popup_hwnd):
        _u.SetForegroundWindow(current.opacity_popup_hwnd)
        return
    controls = INITCOMMONCONTROLSEX(ctypes.sizeof(INITCOMMONCONTROLSEX), ICC_BAR_CLASSES)
    _c.InitCommonControlsEx(ctypes.byref(controls))
    hinstance = _k.GetModuleHandleW(None)
    class_name = "CodexQuotaOpacityWindow"
    wc = WNDCLASS()
    wc.lpfnWndProc = ctypes.cast(_OPACITY_POPUP_WNDPROC, ctypes.c_void_p)
    wc.hInstance = hinstance
    wc.hCursor = _u.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
    wc.hbrBackground = 16  # COLOR_BTNFACE + 1
    wc.lpszClassName = class_name
    _u.RegisterClassW(ctypes.byref(wc))

    width, height = 320, 92
    point = wintypes.POINT()
    _u.GetCursorPos(ctypes.byref(point))
    x, y = point.x, point.y
    for left, top, right, bottom in _monitor_work_areas():
        if left <= point.x < right and top <= point.y < bottom:
            x = min(max(point.x, left), right - width)
            y = min(max(point.y, top), bottom - height)
            break
    hwnd = _u.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        class_name,
        f"透明度: {current.opacity}%",
        WS_POPUP | WS_CAPTION | WS_SYSMENU,
        x,
        y,
        width,
        height,
        current.hwnd,
        None,
        hinstance,
        None,
    )
    if not hwnd:
        return
    current.opacity_popup_hwnd = hwnd
    slider = _u.CreateWindowExW(
        0,
        TRACKBAR_CLASS,
        "",
        WS_CHILD | WS_VISIBLE | TBS_AUTOTICKS,
        10,
        8,
        width - 28,
        42,
        hwnd,
        None,
        hinstance,
        None,
    )
    current.opacity_slider_hwnd = slider
    _u.SendMessageW(slider, TBM_SETRANGE, 1, OPACITY_MIN | (OPACITY_MAX << 16))
    _u.SendMessageW(slider, TBM_SETTICFREQ, 10, 0)
    _u.SendMessageW(slider, TBM_SETPOS, 1, current.opacity)
    _u.ShowWindow(hwnd, SW_SHOW)
    _u.SetForegroundWindow(hwnd)


def _overlay_wndproc(hwnd, msg, wp, lp):
    current = overlay
    if current is None:
        return _u.DefWindowProcW(hwnd, msg, wp, lp)
    if msg == WM_PAINT:
        ps = PAINTSTRUCT()
        hdc = _u.BeginPaint(hwnd, ctypes.byref(ps))
        try:
            _paint_overlay(current, hwnd, hdc)
        finally:
            _u.EndPaint(hwnd, ctypes.byref(ps))
        return 0
    if msg == WM_ERASEBKGND:
        return 1
    if msg == WM_NCHITTEST and not current.click_through:
        return HTCAPTION
    if msg == WM_NCLBUTTONDBLCLK:
        current.cycle_layout()
        return 0
    if msg == WM_NCRBUTTONUP:
        current.show_context_menu()
        return 0
    if msg == WM_EXITSIZEMOVE:
        current.persist_position()
        return 0
    if msg in (WM_DISPLAYCHANGE, WM_DPICHANGED, WM_APP_OVERLAY_UPDATE):
        current.apply_window_state(reposition=msg in (WM_DISPLAYCHANGE, WM_DPICHANGED))
        return 0
    if msg == WM_APP_OVERLAY_SHOW:
        _u.ShowWindow(hwnd, SW_SHOWNA)
        return 0
    if msg == WM_APP_OVERLAY_HIDE:
        _u.ShowWindow(hwnd, SW_HIDE)
        return 0
    if msg == WM_APP_OVERLAY_OPACITY:
        _show_opacity_popup(current)
        return 0
    if msg == WM_CLOSE:
        _u.DestroyWindow(hwnd)
        return 0
    if msg == WM_DESTROY:
        current.hwnd = None
        _u.PostQuitMessage(0)
        return 0
    return _u.DefWindowProcW(hwnd, msg, wp, lp)


_OVERLAY_WNDPROC = WNDPROC(_overlay_wndproc)


def _configure_win32_signatures():
    signatures = [
        (_u.DefWindowProcW, [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM], LRESULT),
        (_u.BeginPaint, [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)], wintypes.HDC),
        (_u.EndPaint, [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)], wintypes.BOOL),
        (_u.DestroyWindow, [wintypes.HWND], wintypes.BOOL),
        (_u.PostQuitMessage, [ctypes.c_int], None),
        (_u.PostMessageW, [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM], wintypes.BOOL),
        (_u.SendMessageW, [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM], LRESULT),
        (_u.SetWindowTextW, [wintypes.HWND, wintypes.LPCWSTR], wintypes.BOOL),
        (_u.SetForegroundWindow, [wintypes.HWND], wintypes.BOOL),
        (_u.IsWindow, [wintypes.HWND], wintypes.BOOL),
        (_u.ShowWindow, [wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        (_u.InvalidateRect, [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL], wintypes.BOOL),
        (_u.GetClientRect, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
        (_u.GetWindowRect, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
        (_u.SetWindowPos, [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        (_u.GetWindowLongPtrW, [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t),
        (_u.SetWindowLongPtrW, [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
        (_u.SetLayeredWindowAttributes, [wintypes.HWND, wintypes.COLORREF,
                                         wintypes.BYTE, wintypes.DWORD], wintypes.BOOL),
        (_u.CreateWindowExW, [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                              wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                              wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HWND),
        (_u.RegisterClassW, [ctypes.POINTER(WNDCLASS)], wintypes.ATOM),
        (_u.GetMessageW, [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                          wintypes.UINT, wintypes.UINT], wintypes.BOOL),
        (_u.TranslateMessage, [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
        (_u.DispatchMessageW, [ctypes.POINTER(wintypes.MSG)], LRESULT),
        (_u.LoadCursorW, [wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HANDLE),
        (_u.EnumDisplayMonitors, [wintypes.HDC, ctypes.c_void_p,
                                  MONITORENUMPROC, LPARAM], wintypes.BOOL),
        (_u.GetMonitorInfoW, [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)], wintypes.BOOL),
        (_u.GetCursorPos, [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
        (_u.FillRect, [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH], ctypes.c_int),
        (_u.CreatePopupMenu, [], wintypes.HMENU),
        (_u.AppendMenuW, [wintypes.HMENU, wintypes.UINT, WPARAM,
                          wintypes.LPCWSTR], wintypes.BOOL),
        (_u.TrackPopupMenu, [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.HWND,
                             ctypes.c_void_p], wintypes.UINT),
        (_u.DestroyMenu, [wintypes.HMENU], wintypes.BOOL),
        (_g.SetTextColor, [wintypes.HDC, wintypes.COLORREF], wintypes.COLORREF),
        (_g.SetBkMode, [wintypes.HDC, ctypes.c_int], ctypes.c_int),
        (_g.SelectObject, [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ),
        (_g.DeleteObject, [wintypes.HGDIOBJ], wintypes.BOOL),
        (_g.TextOutW, [wintypes.HDC, ctypes.c_int, ctypes.c_int,
                       wintypes.LPCWSTR, ctypes.c_int], wintypes.BOOL),
        (_g.CreateSolidBrush, [wintypes.COLORREF], wintypes.HBRUSH),
        (_g.CreateFontW, [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 +
                         [wintypes.LPCWSTR], wintypes.HGDIOBJ),
        (_k.GetModuleHandleW, [wintypes.LPCWSTR], wintypes.HINSTANCE),
    ]
    for function, argtypes, restype in signatures:
        function.argtypes = argtypes
        function.restype = restype
    _c.InitCommonControlsEx.argtypes = [ctypes.POINTER(INITCOMMONCONTROLSEX)]
    _c.InitCommonControlsEx.restype = wintypes.BOOL


_configure_win32_signatures()


def _overlay_start(self):
    if getattr(self, "_thread", None) and self._thread.is_alive():
        return
    self._ready = threading.Event()
    self._thread = threading.Thread(target=self._run, daemon=True, name="CodexQuotaOverlay")
    self._thread.start()
    self._ready.wait(3)


def _overlay_run(self):
    try:
        hinstance = _k.GetModuleHandleW(None)
        class_name = "CodexQuotaOverlayWindow"
        wc = WNDCLASS()
        wc.style = CS_DBLCLKS
        wc.lpfnWndProc = ctypes.cast(_OVERLAY_WNDPROC, ctypes.c_void_p)
        wc.hInstance = hinstance
        wc.hCursor = _u.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        wc.lpszClassName = class_name
        _u.RegisterClassW(ctypes.byref(wc))
        rows = make_display_rows(state.get("primary"), state.get("secondary"), SHOW_MODE)
        width, height = overlay_size(self.layout, len(rows))
        self.x, self.y = clamp_overlay_position(
            self.x, self.y, width, height, _monitor_work_areas()
        )
        ex_style = WS_EX_TOOLWINDOW | WS_EX_LAYERED
        if self.click_through:
            ex_style |= WS_EX_TRANSPARENT
        style = WS_POPUP | (WS_VISIBLE if self.visible else 0)
        self.hwnd = _u.CreateWindowExW(
            ex_style, class_name, "Codex 额度", style,
            self.x, self.y, width, height, None, None, hinstance, None,
        )
        if not self.hwnd:
            return
        alpha = round(self.opacity * 255 / 100)
        _u.SetLayeredWindowAttributes(self.hwnd, 0, alpha, LWA_ALPHA)
        self.apply_window_state(reposition=True)
    except Exception:
        import traceback
        self.startup_error = traceback.format_exc()
    finally:
        self._ready.set()
    if not self.hwnd:
        return
    message = wintypes.MSG()
    while _u.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        _u.TranslateMessage(ctypes.byref(message))
        _u.DispatchMessageW(ctypes.byref(message))


def _overlay_apply_window_state(self, reposition=False):
    if not self.hwnd:
        return
    rows = make_display_rows(state.get("primary"), state.get("secondary"), SHOW_MODE)
    width, height = overlay_size(self.layout, len(rows))
    ex_style = _u.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
    ex_style |= WS_EX_TOOLWINDOW | WS_EX_LAYERED
    if self.click_through:
        ex_style |= WS_EX_TRANSPARENT
    else:
        ex_style &= ~WS_EX_TRANSPARENT
    _u.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex_style)
    alpha = round(self.opacity * 255 / 100)
    _u.SetLayeredWindowAttributes(self.hwnd, 0, alpha, LWA_ALPHA)
    if reposition:
        self.x, self.y = clamp_overlay_position(
            self.x, self.y, width, height, _monitor_work_areas()
        )
    insert_after = HWND_TOPMOST if self.topmost else HWND_NOTOPMOST
    _u.SetWindowPos(
        self.hwnd, insert_after, self.x, self.y, width, height, SWP_NOACTIVATE
    )
    _u.ShowWindow(self.hwnd, SW_SHOWNA if self.visible else SW_HIDE)
    _u.InvalidateRect(self.hwnd, None, True)


def _overlay_persist_position(self):
    if not self.hwnd:
        return
    rect = wintypes.RECT()
    if _u.GetWindowRect(self.hwnd, ctypes.byref(rect)):
        self.x, self.y = rect.left, rect.top
        self._persist("x", self.x)
        self._persist("y", self.y)


def _overlay_set_visible(self, visible):
    self.visible = bool(visible)
    self._persist("overlay_visible", self.visible)
    if self.hwnd:
        message = WM_APP_OVERLAY_SHOW if self.visible else WM_APP_OVERLAY_HIDE
        _u.PostMessageW(self.hwnd, message, 0, 0)


def _overlay_invalidate(self):
    self._notify_changed()


def _overlay_show_opacity_slider(self):
    if self.hwnd:
        _u.PostMessageW(self.hwnd, WM_APP_OVERLAY_OPACITY, 0, 0)


def _overlay_stop(self):
    if self.hwnd:
        _u.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
    thread = getattr(self, "_thread", None)
    if thread and thread.is_alive():
        thread.join(timeout=2)


def overlay_menu_labels(layout, accent_color):
    layout_labels = {
        "full": "完整横版",
        "micro": "极简横条",
        "vertical": "紧凑竖版",
    }
    color_labels = {
        "green": "绿色",
        "cyan": "青色",
        "orange": "橙色",
        "white": "白色",
    }
    return (
        f"样式: {layout_labels.get(layout, layout_labels['full'])}",
        f"配色: {color_labels.get(accent_color, color_labels['green'])}",
        "调整透明度…",
        "鼠标穿透",
        "隐藏悬浮窗",
    )


def _overlay_context_menu(self):
    if not self.hwnd or self.click_through:
        return
    menu = _u.CreatePopupMenu()
    labels = overlay_menu_labels(self.layout, self.accent_color)
    try:
        _u.AppendMenuW(menu, MF_STRING, 101, labels[0])
        _u.AppendMenuW(menu, MF_STRING, 121, labels[1])
        _u.AppendMenuW(menu, MF_STRING, 123, labels[2])
        _u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        _u.AppendMenuW(menu, MF_STRING, 111, labels[3])
        _u.AppendMenuW(menu, MF_STRING, 112, labels[4])
        point = wintypes.POINT()
        _u.GetCursorPos(ctypes.byref(point))
        command = _u.TrackPopupMenu(
            menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, point.x, point.y, 0, self.hwnd, None
        )
        if command == 101:
            self.cycle_layout()
        elif command == 111:
            self.set_click_through(True)
        elif command == 112:
            self.set_visible(False)
        elif command == 121:
            self.set_accent_color(next_choice(tuple(COLOR_PRESETS), self.accent_color))
        elif command == 123:
            self.show_opacity_slider()
        if icon is not None:
            icon.update_menu()
    finally:
        _u.DestroyMenu(menu)


OverlayWindow.start = _overlay_start
OverlayWindow._run = _overlay_run
OverlayWindow.apply_window_state = _overlay_apply_window_state
OverlayWindow.persist_position = _overlay_persist_position
OverlayWindow.set_visible = _overlay_set_visible
OverlayWindow.invalidate = _overlay_invalidate
OverlayWindow.show_opacity_slider = _overlay_show_opacity_slider
OverlayWindow.stop = _overlay_stop
OverlayWindow.show_context_menu = _overlay_context_menu


class RefreshCoordinator:
    def __init__(self, callback):
        self.callback = callback
        self._lock = threading.Lock()

    def try_begin(self):
        return self._lock.acquire(blocking=False)

    def end(self):
        if self._lock.locked():
            self._lock.release()

    def run(self):
        if not self.try_begin():
            return False
        try:
            self.callback()
            return True
        finally:
            self.end()


# ---------- 交互 ----------
def on_detail_menu(icon_obj, item):
    """显示常驻悬浮窗。"""
    if overlay is not None:
        overlay.set_visible(True)
        icon_obj.update_menu()


# ---------- 双击托盘图标弹详情 ----------
# 此 pystray 版本没有 on_double_click API；左键抬起走 default 菜单项路径
# （WM_LBUTTONUP -> Icon.__call__ -> Menu.__call__ -> default 项 action）。
# 成熟方案（参考 PySimpleGUI 官方托盘 psgtray）：菜单里放一个 default=True、
# visible=False 的 MenuItem，其 action 用时间差（500ms）判定双击。因托盘窗口
# 类无 CS_DBLCLKS 风格，真实双击 = 两次 WM_LBUTTONUP，间隔 < 500ms 即双击。
_DCLICK_MS = 500
_last_activate = 0.0
_activate_lock = threading.Lock()


def on_icon_activate(icon_obj, item):
    """双击托盘图标时显示悬浮窗。"""
    global _last_activate
    now = time.time()
    with _activate_lock:
        if _last_activate and (now - _last_activate) * 1000 < _DCLICK_MS:
            _last_activate = 0.0
            if overlay is not None:
                overlay.set_visible(True)
                icon_obj.update_menu()
        else:
            _last_activate = now                                       # 单击：仅记时，不弹


def update_views():
    if icon is not None:
        try:
            icon.icon = make_icon()
            icon.title = make_title()
        except Exception:
            pass
    if overlay is not None:
        overlay.invalidate()


def _refresh_once():
    fetch()
    update_views()


refresh_coordinator = RefreshCoordinator(_refresh_once)
stop_event = threading.Event()


def refresh_now(icon_obj, item):
    threading.Thread(
        target=refresh_coordinator.run, daemon=True, name="CodexQuotaManualRefresh"
    ).start()


def toggle_overlay(icon_obj, item):
    if overlay is not None:
        overlay.set_visible(not overlay.visible)
        icon_obj.update_menu()


def select_layout(layout):
    def callback(icon_obj, item):
        if overlay is not None:
            overlay.set_layout(layout)
            icon_obj.update_menu()
    return callback


def next_choice(choices, current):
    try:
        return choices[(choices.index(current) + 1) % len(choices)]
    except ValueError:
        return choices[0]


def select_appearance(name, value):
    def callback(icon_obj, item):
        if overlay is not None:
            getattr(overlay, f"set_{name}")(value)
            icon_obj.update_menu()
    return callback


def show_opacity_slider(icon_obj, item):
    if overlay is not None:
        overlay.show_opacity_slider()


def appearance_checked(name, value):
    return lambda item: bool(overlay and getattr(overlay, name) == value)


def appearance_menu(name, choices):
    return Menu(
        *(
            MenuItem(
                label,
                select_appearance(name, value),
                checked=appearance_checked(name, value),
                radio=True,
            )
            for value, label in choices
        )
    )


def toggle_topmost(icon_obj, item):
    if overlay is not None:
        overlay.set_topmost(not overlay.topmost)
        icon_obj.update_menu()


def toggle_click_through(icon_obj, item):
    if overlay is not None:
        overlay.set_click_through(not overlay.click_through)
        icon_obj.update_menu()


def toggle_mode(icon_obj, item):
    global SHOW_MODE
    SHOW_MODE = "free" if SHOW_MODE == "used" else "used"
    save_setting("show_mode", SHOW_MODE)
    update_views()
    icon_obj.update_menu()


def quit_app(icon_obj, item):
    stop_event.set()
    if overlay is not None:
        overlay.stop()
    icon.stop()


def refresh_loop():
    while not stop_event.wait(REFRESH_INTERVAL):
        refresh_coordinator.run()


# ---------- 单实例保护 ----------
_single_instance_handle = None
_mutex_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_mutex_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_mutex_kernel32.CreateMutexW.restype = wintypes.HANDLE
_mutex_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_mutex_kernel32.CloseHandle.restype = wintypes.BOOL
_ERROR_ALREADY_EXISTS = 183


def ensure_single_instance():
    global _single_instance_handle
    handle = _mutex_kernel32.CreateMutexW(None, False, "Local\\CodexQuotaMonitor")
    if not handle:
        return False
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        _mutex_kernel32.CloseHandle(handle)
        return False
    _single_instance_handle = handle
    return True


# ---------- 开机启动（HKCU Run 键，纯 winreg，无 COM 依赖） ----------
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "CodexQuotaMonitor"
_MONITOR_PATH = os.path.abspath(__file__)


def _run_value():
    executable = sys.executable
    if os.path.basename(executable).lower() == "python.exe":
        candidate = os.path.join(os.path.dirname(executable), "pythonw.exe")
        if os.path.exists(candidate):
            executable = candidate
    return '"%s" "%s"' % (executable, _MONITOR_PATH)


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, _RUN_NAME)
        return value == _run_value()
    except OSError:
        return False


def set_startup(enable):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, _RUN_NAME, 0, winreg.REG_SZ, _run_value())
            else:
                try:
                    winreg.DeleteValue(k, _RUN_NAME)
                except OSError:
                    pass
    except OSError as e:
        ctypes.windll.user32.MessageBoxW(0, str(e), "开机启动设置失败", 0x10)


def toggle_startup(icon_obj, item):
    set_startup(not startup_enabled())
    try:
        icon_obj.update_menu()
    except Exception:
        pass


def main():
    global icon, overlay, SHOW_MODE
    if not ensure_single_instance():
        return  # 静默退出
    settings = load_settings()
    SHOW_MODE = settings["show_mode"]
    fetch()
    overlay = OverlayWindow(settings)
    overlay.start()
    icon = Icon("codex_quota", icon=make_icon(), title=make_title())
    icon.menu = Menu(
        MenuItem(
            lambda item: "悬浮窗: 隐藏" if overlay and overlay.visible else "悬浮窗: 显示",
            toggle_overlay,
        ),
        MenuItem(
            "悬浮样式",
            Menu(
                MenuItem(
                    "完整横版",
                    select_layout("full"),
                    checked=lambda item: bool(overlay and overlay.layout == "full"),
                    radio=True,
                ),
                MenuItem(
                    "极简横条",
                    select_layout("micro"),
                    checked=lambda item: bool(overlay and overlay.layout == "micro"),
                    radio=True,
                ),
                MenuItem(
                    "紧凑竖版",
                    select_layout("vertical"),
                    checked=lambda item: bool(overlay and overlay.layout == "vertical"),
                    radio=True,
                ),
            ),
        ),
        MenuItem(
            "外观",
            Menu(
                MenuItem(
                    "配色",
                    appearance_menu(
                        "accent_color",
                        (("green", "绿色"), ("cyan", "青色"), ("orange", "橙色"), ("white", "白色")),
                    ),
                ),
                MenuItem("调整透明度…", show_opacity_slider),
            ),
        ),
        MenuItem(
            lambda item: "鼠标穿透: 开" if overlay and overlay.click_through else "鼠标穿透: 关",
            toggle_click_through,
        ),
        MenuItem("刷新", refresh_now),
        MenuItem(
            "更多设置",
            Menu(
                MenuItem(
                    lambda item: "始终置顶: 开" if overlay and overlay.topmost else "始终置顶: 关",
                    toggle_topmost,
                ),
                MenuItem(
                    lambda item: "显示口径: 可用" if SHOW_MODE == "free" else "显示口径: 已用",
                    toggle_mode,
                ),
                MenuItem(
                    lambda item: "开机启动: 开" if startup_enabled() else "开机启动: 关",
                    toggle_startup,
                ),
            ),
        ),
        Menu.SEPARATOR,
        MenuItem("退出", quit_app),
        MenuItem("", on_icon_activate, default=True, visible=False),
    )
    threading.Thread(target=refresh_loop, daemon=True).start()
    try:
        icon.run()
    finally:
        stop_event.set()
        if overlay is not None:
            overlay.stop()
        global _single_instance_handle
        if _single_instance_handle is not None:
            _mutex_kernel32.CloseHandle(_single_instance_handle)
            _single_instance_handle = None


def show_error(title, msg):
    # pythonw 无控制台，用系统弹窗暴露崩溃
    try:
        ctypes.windll.user32.MessageBoxW(0, str(msg), str(title), 0x10)  # MB_ICONERROR
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        show_error("Codex 额度监视器出错", traceback.format_exc())
