"""Windows screen capture with the same contract as native/ScreenBridge.swift.

One frame per request, scaled to 1440 px wide, PNG in memory only. The companion's
own windows are excluded from the frame with WDA_EXCLUDEFROMCAPTURE (Windows 10 2004+),
only for the duration of the capture so it stays visible in screen sharing.
"""
import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import os
import struct
import time
import zlib
from .windows_desktop import DENIED_EXECUTABLES, WindowsDesktopBridge, _Win32

CAPTURE_WIDTH = 1440
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11
SRCCOPY = 0x00CC0020
HALFTONE = 4
DIB_RGB_COLORS = 0
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]


def png(width, height, bgra):
    """Encode top-down 32-bit BGRA pixels as an RGB PNG."""
    rgb = bytearray(width*height*3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    stride = width*3
    raw = b''.join(b'\x00'+bytes(rgb[row*stride:(row+1)*stride]) for row in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6))+chunk(b'IEND', b''))


class WindowsScreenBridge:
    def __init__(self):
        # Window list only; the app catalog is not needed for capture.
        self.desktop = WindowsDesktopBridge(win32=_Win32())
        self.user32 = self.desktop.win32.user32
        self.gdi32 = ctypes.WinDLL('gdi32')
        self.shcore = ctypes.WinDLL('shcore')
        u, g = self.user32, self.gdi32
        u.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        u.MonitorFromPoint.restype = wintypes.HMONITOR
        u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
        u.GetDC.argtypes = [wintypes.HWND]
        u.GetDC.restype = wintypes.HDC
        u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        g.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g.CreateCompatibleDC.restype = wintypes.HDC
        g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g.SelectObject.restype = wintypes.HGDIOBJ
        g.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
        g.StretchBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        g.GdiFlush.argtypes = []
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g.DeleteDC.argtypes = [wintypes.HDC]
        self.shcore.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, ctypes.c_int, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]

    def call(self, *args):
        if '--request-access' in args:
            # Windows has no screen-recording permission; capture only needs exclusion support.
            return {'granted': True}
        values = dict(zip(args[::2], args[1::2]))
        return self.capture(float(values.get('--x', 0)), float(values.get('--y', 0)))

    def own_windows(self):
        own = []
        callback = self.desktop.win32.EnumWindowsProc(
            lambda hwnd, _: own.append(hwnd) or True if self.desktop.win32.pid(hwnd) == os.getpid() else True)
        self.user32.EnumWindows(callback, 0)
        return [h for h in own if self.user32.IsWindowVisible(h)]

    def monitor(self, x, y):
        """Monitor whose top-left matches Qt's screen origin (Qt keeps origins in native pixels)."""
        handle = self.user32.MonitorFromPoint(wintypes.POINT(int(x)+1, int(y)+1), MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if not handle or not self.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            raise RuntimeError('No display is available to capture.')
        dpi_x, dpi_y = wintypes.UINT(96), wintypes.UINT(96)
        self.shcore.GetDpiForMonitor(handle, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        return info.rcMonitor, (dpi_x.value or 96)/96

    def capture(self, x, y):
        foreground = self.user32.GetForegroundWindow()
        if foreground:
            path = self.desktop.win32.executable(self.desktop.win32.pid(foreground))
            if path and path.rsplit('\\', 1)[-1].lower() in DENIED_EXECUTABLES:
                return {'error': 'Screen vision paused while a protected app is active.'}
        rect, scale = self.monitor(x, y)
        width, height = rect.right-rect.left, rect.bottom-rect.top
        out_w, out_h = CAPTURE_WIDTH, max(1, round(CAPTURE_WIDTH*height/width))
        own = self.own_windows()
        excluded = [h for h in own if self.user32.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE)]
        try:
            if len(excluded) != len(own):
                return {'error': 'The companion is visible but could not be excluded. Hide its panels and retry.'}
            time.sleep(0.12)  # let the compositor drop the excluded windows from the next frame
            pixels = self.grab(rect, out_w, out_h)
        finally:
            for hwnd in excluded:
                self.user32.SetWindowDisplayAffinity(hwnd, WDA_NONE)
        # Logical monitor bounds, the same coordinates Qt and the window list use.
        screen = {'x': x, 'y': y, 'width': width/scale, 'height': height/scale}
        windows = [w for w in self.desktop.windows()
                   if w['bounds']['x'] < x+screen['width'] and w['bounds']['x']+w['bounds']['width'] > x
                   and w['bounds']['y'] < y+screen['height'] and w['bounds']['y']+w['bounds']['height'] > y][:14]
        return {'image_data': 'data:image/png;base64,'+base64.b64encode(png(out_w, out_h, pixels)).decode(),
                'screen': screen,
                'captured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'windows': [{'app': w['name'], 'title': w['title']} for w in windows],
                'companion_excluded': True}

    def grab(self, rect, out_w, out_h):
        screen = self.user32.GetDC(None)
        memory = self.gdi32.CreateCompatibleDC(screen)
        header = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=out_w, biHeight=-out_h,
                                  biPlanes=1, biBitCount=32, biCompression=0)
        bits = ctypes.c_void_p()
        bitmap = self.gdi32.CreateDIBSection(memory, ctypes.byref(header), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        try:
            if not bitmap:
                raise RuntimeError('Screen capture failed. Try again.')
            previous = self.gdi32.SelectObject(memory, bitmap)
            self.gdi32.SetStretchBltMode(memory, HALFTONE)
            ok = self.gdi32.StretchBlt(memory, 0, 0, out_w, out_h, screen, rect.left, rect.top,
                                       rect.right-rect.left, rect.bottom-rect.top, SRCCOPY)
            self.gdi32.GdiFlush()
            data = ctypes.string_at(bits, out_w*out_h*4) if ok else None
            self.gdi32.SelectObject(memory, previous)
            if data is None:
                raise RuntimeError('Screen capture failed. Try again.')
            return data
        finally:
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            self.gdi32.DeleteDC(memory)
            self.user32.ReleaseDC(None, screen)
