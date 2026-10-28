from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Control:
    handle: int
    class_name: str
    text: str
    visible: bool
    enabled: bool
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def public(self) -> dict[str, Any]:
        item = asdict(self)
        item["handle"] = f"0x{self.handle:X}"
        item["text"] = self.text[:2000]
        item["width"] = self.width
        item["height"] = self.height
        return item


class WindowsConsole:
    """Read same-user Rescue console state without a mutation method."""

    def __init__(self, window_class: str) -> None:
        if not hasattr(ctypes, "WinDLL"):
            raise RuntimeError("Rescue console control is only available on Windows")
        self.window_class = window_class
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self.enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.EnumWindows.argtypes = [self.enum_proc_type, wintypes.LPARAM]
        self.user32.EnumChildWindows.argtypes = [wintypes.HWND, self.enum_proc_type, wintypes.LPARAM]
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    def _class_name(self, handle: int) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        self.user32.GetClassNameW(wintypes.HWND(handle), buffer, len(buffer))
        return buffer.value

    def _text(self, handle: int) -> str:
        length = min(65535, max(0, int(self.user32.GetWindowTextLengthW(wintypes.HWND(handle)))))
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(wintypes.HWND(handle), buffer, len(buffer))
        return buffer.value.replace("\x00", "").strip()

    def _control(self, handle: int) -> Control:
        rect = wintypes.RECT()
        self.user32.GetWindowRect(wintypes.HWND(handle), ctypes.byref(rect))
        return Control(
            handle=handle,
            class_name=self._class_name(handle),
            text=self._text(handle),
            visible=bool(self.user32.IsWindowVisible(wintypes.HWND(handle))),
            enabled=bool(self.user32.IsWindowEnabled(wintypes.HWND(handle))),
            left=int(rect.left),
            top=int(rect.top),
            right=int(rect.right),
            bottom=int(rect.bottom),
        )

    def main_windows(self) -> list[Control]:
        handles: list[int] = []

        @self.enum_proc_type
        def callback(handle: int, _lparam: int) -> bool:
            if self._class_name(int(handle)) == self.window_class:
                handles.append(int(handle))
            return True

        self.user32.EnumWindows(callback, 0)
        return [self._control(handle) for handle in handles]

    def child_controls(self, main_handle: int) -> list[Control]:
        handles: list[int] = []

        @self.enum_proc_type
        def callback(handle: int, _lparam: int) -> bool:
            handles.append(int(handle))
            return True

        self.user32.EnumChildWindows(wintypes.HWND(main_handle), callback, 0)
        return [self._control(handle) for handle in handles]

    def snapshot(self, *, include_hidden: bool = False, limit: int = 300) -> dict[str, Any]:
        windows = self.main_windows()
        if not windows:
            return {
                "running": False,
                "windowClass": self.window_class,
                "windows": [],
                "controls": [],
                "noSession": True,
                "chatDisabled": True,
                "chatInputHandles": [],
                "visibleTexts": [],
            }
        main = windows[0]
        controls = self.child_controls(main.handle)
        selected = [c for c in controls if include_hidden or c.visible][: max(1, min(limit, 1000))]
        visible = [c for c in controls if c.visible]
        visible_texts = list(dict.fromkeys(c.text for c in visible if c.text))
        lowered = "\n".join(visible_texts).casefold()
        inputs = [
            c
            for c in visible
            if c.enabled and c.class_name.casefold() == "lmitc_richedithunspell"
        ]
        text_controls = [
            c
            for c in visible
            if ("edit" in c.class_name.casefold() or "rich" in c.class_name.casefold()) and c.text
        ]
        return {
            "running": True,
            "processId": self._process_id(main.handle),
            "mainWindow": main.public(),
            "windows": [item.public() for item in windows],
            "controls": [item.public() for item in selected],
            "noSession": "no session" in lowered,
            "chatDisabled": "chat disabled" in lowered,
            "chatInputHandles": [f"0x{item.handle:X}" for item in inputs],
            "chatText": [item.text[:16000] for item in text_controls],
            "visibleTexts": visible_texts[:300],
        }

    def _process_id(self, handle: int) -> int:
        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(wintypes.HWND(handle), ctypes.byref(process_id))
        return int(process_id.value)
