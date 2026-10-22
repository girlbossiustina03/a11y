"""Windows desktop bridge with the same interface as MacDesktopBridge.

Reads only window metadata (titles, owners, bounds) through Win32; never window
contents. Actions are limited to opening catalog apps, focusing an app, closing an
observed window and asking an app to quit. Control pressing is macOS-only for now.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import threading
import time

DENIED_EXECUTABLES = {'1password.exe', 'bitwarden.exe', 'keepass.exe', 'keepassxc.exe', 'dashlane.exe',
                      'lastpass.exe', 'credentialuibroker.exe'}
# Hosts and shell surfaces that are not apps the user would ask for by name.
IGNORED_EXECUTABLES = {'textinputhost.exe', 'shellexperiencehost.exe', 'startmenuexperiencehost.exe',
                       'searchhost.exe', 'lockapp.exe', 'systemsettingsbroker.exe'}
# Built-in apps addressed by URI or by an executable on PATH.
BUILTIN_APPS = [
    ('Settings', 'ms-settings:'), ('Calculator', 'calc.exe'), ('Notepad', 'notepad.exe'),
    ('File Explorer', 'explorer.exe'), ('Task Manager', 'taskmgr.exe'), ('Paint', 'mspaint.exe'),
    ('Command Prompt', 'cmd.exe'), ('PowerShell', 'powershell.exe'), ('Control Panel', 'control.exe'),
    ('Snipping Tool', 'ms-screenclip:'), ('Microsoft Store', 'ms-windows-store:'),
    ('Clock', 'ms-clock:'), ('Camera', 'microsoft.windows.camera:'),
]
SKIPPED_SHORTCUT_WORDS = ('uninstall', 'readme', 'read me', 'help', 'documentation', 'license',
                          'release notes', 'website', 'manual')
CATALOG_TTL = 600
WM_CLOSE = 0x0010
SW_RESTORE = 9
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _Win32:
    def __init__(self):
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.dwmapi = ctypes.WinDLL('dwmapi')
        self.version = ctypes.WinDLL('version')
        u, k = self.user32, self.kernel32
        self.EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [self.EnumWindowsProc, wintypes.LPARAM]
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
        u.GetWindow.restype = wintypes.HWND
        u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
        u.GetDpiForWindow.argtypes = [wintypes.HWND]
        u.GetDpiForWindow.restype = ctypes.c_uint
        u.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        u.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
        self.dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        self.version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]

    def top_level_windows(self):
        found = []
        callback = self.EnumWindowsProc(lambda hwnd, _: found.append(hwnd) or True)
        self.user32.EnumWindows(callback, 0)
        return found

    def title(self, hwnd):
        length = self.user32.GetWindowTextLengthW(hwnd)
        if not length:
            return ''
        buffer = ctypes.create_unicode_buffer(length+1)
        self.user32.GetWindowTextW(hwnd, buffer, length+1)
        return buffer.value

    def pid(self, hwnd):
        value = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(value))
        return value.value

    def is_app_window(self, hwnd):
        u = self.user32
        if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, GW_OWNER):
            return False
        if u.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return False
        cloaked = wintypes.DWORD()
        self.dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return not cloaked.value

    def bounds(self, hwnd):
        rect = wintypes.RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        # Qt and the prompts use logical (device-independent) coordinates. DPI-aware
        # callers (Qt sets per-monitor awareness) get physical pixels; unaware callers
        # already get virtualized logical ones.
        aware = self.user32.GetAwarenessFromDpiAwarenessContext(self.user32.GetThreadDpiAwarenessContext())
        scale = (self.user32.GetDpiForWindow(hwnd) or 96)/96 if aware > 0 else 1
        return {'x': rect.left/scale, 'y': rect.top/scale,
                'width': (rect.right-rect.left)/scale, 'height': (rect.bottom-rect.top)/scale}

    def executable(self, pid):
        handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ''
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
            return ''
        finally:
            self.kernel32.CloseHandle(handle)

    def description(self, path):
        """FileDescription from version info, e.g. 'Google Chrome'; empty when absent."""
        size = self.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ''
        data = ctypes.create_string_buffer(size)
        if not self.version.GetFileVersionInfoW(path, 0, size, data):
            return ''
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not self.version.VerQueryValueW(data, '\\VarFileInfo\\Translation', ctypes.byref(pointer), ctypes.byref(length)) or length.value < 4:
            return ''
        language, codepage = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ushort*2)).contents
        key = '\\StringFileInfo\\%04x%04x\\FileDescription' % (language, codepage)
        if not self.version.VerQueryValueW(data, key, ctypes.byref(pointer), ctypes.byref(length)) or not length.value:
            return ''
        return ctypes.wstring_at(pointer, length.value).rstrip('\x00').strip()


class WindowsDesktopBridge:
    def __init__(self, directory=None, *, win32=None):
        self.win32 = win32 or _Win32()
        self.own_pid = os.getpid()
        self.lock = threading.Lock()
        self.catalog_cache = ([], {}, 0.0)
        self.names = {}
        if win32 is None:
            # Reading the Start menu takes a few seconds; do it before the first request needs it.
            threading.Thread(target=self.catalog_entries, daemon=True).start()

    # --- Observation ---
    def app_name(self, path):
        if path not in self.names:
            stem = PureWindowsPath(path).stem
            self.names[path] = (self.win32.description(path) or stem)[:100]
        return self.names[path]

    def windows(self):
        """Visible top-level app windows in z-order (topmost first)."""
        result = []
        for hwnd in self.win32.top_level_windows():
            if not self.win32.is_app_window(hwnd):
                continue
            title = self.win32.title(hwnd)
            pid = self.win32.pid(hwnd)
            if not title or pid == self.own_pid:
                continue
            path = self.win32.executable(pid)
            executable = PureWindowsPath(path).name.lower() if path else ''
            if not executable or executable in DENIED_EXECUTABLES or executable in IGNORED_EXECUTABLES:
                continue
            rect = self.win32.bounds(hwnd)
            if not rect or rect['width'] <= 1 or rect['height'] <= 1:
                continue
            if executable == 'applicationframehost.exe':
                # Store apps (Settings, Calculator…) are hosted; the title names the app.
                bundle_id, name = 'uwp:'+title.casefold(), title[:100]
            else:
                bundle_id, name = executable, self.app_name(path)
            result.append({'hwnd': int(hwnd), 'pid': pid, 'bundle_id': bundle_id, 'name': name,
                           'title': title[:160], 'bounds': rect})
        return result

    def sample(self):
        windows = self.windows()
        apps, seen = [], set()
        for window in windows:
            if window['bundle_id'] not in seen and len(apps) < 25:
                seen.add(window['bundle_id'])
                apps.append({'name': window['name'], 'bundle_id': window['bundle_id']})
        output = {
            # The installed-app catalog is served by catalog() for launch requests; leaving
            # it out of every observation keeps prompts small enough for local models.
            'platform': 'Windows', 'accessibility': 'granted',
            'available_apps': apps,
            'onscreen_window_candidates': [{'app': w['name'], 'bundle_id': w['bundle_id'], 'bounds': w['bounds']}
                                           for w in windows[:40]],
            'app_windows': [{'window_id': '%s:%d' % (w['bundle_id'], w['hwnd']), 'bundle_id': w['bundle_id'],
                             'name': w['name'], 'title': w['title'], 'bounds': w['bounds'], 'can_close': True}
                            for w in windows[:35]],
            # Control discovery (UI Automation) is not implemented on Windows yet.
            'controls': [],
        }
        foreground = self.win32.user32.GetForegroundWindow()
        if foreground and self.win32.pid(foreground) == self.own_pid:
            output['status'] = 'companion_focused'
            return output
        front = next((w for w in windows if w['hwnd'] == int(foreground or 0)), None)
        if front is None:
            output['status'] = 'unavailable'
            return output
        output['status'] = 'available'
        output['app'] = {'name': front['name'], 'bundle_id': front['bundle_id'], 'pid': front['pid']}
        output['window'] = {'title': front['title'], 'bounds': front['bounds']}
        return output

    def request_access(self):
        # Window metadata needs no special permission on Windows.
        return {'accessibility': 'granted'}

    # --- Installed-app catalog ---
    @staticmethod
    def shortcut_roots():
        roots = []
        for variable in ('PROGRAMDATA', 'APPDATA'):
            base = os.environ.get(variable)
            if base:
                roots.append(Path(base)/'Microsoft'/'Windows'/'Start Menu'/'Programs')
        return roots

    def catalog_entries(self):
        with self.lock:
            apps, targets, created = self.catalog_cache
            if apps and time.monotonic()-created < CATALOG_TTL:
                return apps, targets, created
            apps, targets, names = [], {}, set()
            for name, target in BUILTIN_APPS:
                bundle_id = 'builtin:'+name.casefold().replace(' ', '-')
                apps.append({'bundle_id': bundle_id, 'name': name})
                targets[bundle_id] = target
                names.add(name.casefold())
            # Every Start-menu app, including Store/MSIX apps such as the new Teams,
            # which have no .lnk file. Launched through shell:AppsFolder.
            for item in self.start_apps():
                name, app_id = item['name'], item['app_id']
                if (name.casefold() in names or len(apps) >= 400
                        or any(word in name.casefold() for word in SKIPPED_SHORTCUT_WORDS)):
                    continue
                bundle_id = 'startapp:'+app_id
                apps.append({'bundle_id': bundle_id, 'name': name})
                targets[bundle_id] = 'shell:AppsFolder\\'+app_id
                names.add(name.casefold())
            for root in self.shortcut_roots():
                for shortcut in sorted(root.rglob('*.lnk'))[:600] if root.is_dir() else []:
                    name = shortcut.stem.strip()[:100]
                    if (not name or name.casefold() in names or len(apps) >= 400
                            or any(word in name.casefold() for word in SKIPPED_SHORTCUT_WORDS)):
                        continue
                    bundle_id = 'shortcut:'+str(shortcut)
                    apps.append({'bundle_id': bundle_id, 'name': name})
                    targets[bundle_id] = str(shortcut)
                    names.add(name.casefold())
            apps.sort(key=lambda app: app['name'].casefold())
            self.catalog_cache = (apps, targets, time.monotonic())
            return self.catalog_cache

    @staticmethod
    def start_apps():
        """Name and AppID of each Start-menu app, from Windows' own Get-StartApps."""
        script = ('[Console]::OutputEncoding=[Text.Encoding]::UTF8; '
                  'Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress')
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                    capture_output=True, timeout=15,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            items = json.loads(result.stdout.decode('utf-8-sig') or '[]')
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return []  # .lnk shortcuts below remain a fallback
        if isinstance(items, dict):
            items = [items]
        apps = []
        for item in items if isinstance(items, list) else []:
            name = item.get('Name') if isinstance(item, dict) else None
            app_id = item.get('AppID') if isinstance(item, dict) else None
            if isinstance(name, str) and isinstance(app_id, str) and name.strip() and app_id.strip():
                apps.append({'name': name.strip()[:100], 'app_id': app_id.strip()[:300]})
        return apps

    def catalog(self):
        return self.catalog_entries()[0]

    def running_windows(self, bundle_id):
        """Windows of an app, whether addressed by its running id or by its catalog id."""
        windows = self.windows()
        if not bundle_id.startswith(('builtin:', 'startapp:', 'shortcut:')):
            return [w for w in windows if w['bundle_id'] == bundle_id]
        apps, targets, _ = self.catalog_entries()
        name = next((app['name'].casefold() for app in apps if app['bundle_id'] == bundle_id), None)
        target = PureWindowsPath(targets.get(bundle_id, '')).name.casefold()
        return [w for w in windows if name and (w['name'].casefold() == name or w['bundle_id'] in ('uwp:'+name, target))]

    def app_state(self, bundle_id):
        return {'bundle_id': bundle_id, 'running': bool(self.running_windows(bundle_id))}

    # --- Confirmed actions ---
    def activate(self, bundle_id):
        window = next((w for w in self.windows() if w['bundle_id'] == bundle_id), None)
        if window is None:
            raise RuntimeError('The app is no longer available.')
        user32 = self.win32.user32
        if user32.IsIconic(window['hwnd']):
            user32.ShowWindow(window['hwnd'], SW_RESTORE)
        return {'activated': bool(user32.SetForegroundWindow(window['hwnd'])), 'bundle_id': bundle_id}

    def application_action(self, action):
        kind = action['type']
        if kind == 'launch_app':
            target = self.catalog_entries()[1].get(action['bundle_id'])
            if not target:
                raise RuntimeError('That installed application is no longer available.')
            try:
                os.startfile(target)
            except OSError:
                raise RuntimeError('Windows could not open that application.') from None
            # Give the app a moment to show a window before the result is observed.
            deadline = time.monotonic()+3
            while time.monotonic() < deadline and not self.running_windows(action['bundle_id']):
                time.sleep(0.2)
            return {'submitted': True, 'verification_required': True}
        if kind == 'quit_app':
            windows = [w for w in self.windows() if w['bundle_id'] == action['bundle_id']]
            if not windows:
                raise RuntimeError('That application is no longer running.')
            # Polite close, like macOS terminate(): the app may still ask to save.
            sent = [self.win32.user32.PostMessageW(w['hwnd'], WM_CLOSE, 0, 0) for w in windows]
            self.wait_closed({w['hwnd'] for w in windows})
            return {'submitted': any(sent), 'verification_required': True}
        if kind == 'close_window':
            hwnd = int(action['window_id'].rsplit(':', 1)[1])
            window = next((w for w in self.windows() if w['hwnd'] == hwnd), None)
            expected = action['bounds']
            if (window is None or window['bundle_id'] != action['bundle_id'] or window['title'] != action['window_title']
                    or any(abs(window['bounds'][key]-expected[key]) > 1 for key in ('x', 'y', 'width', 'height'))):
                raise RuntimeError('That window changed or cannot be closed. Request a fresh observation.')
            sent = bool(self.win32.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
            self.wait_closed({hwnd})
            return {'submitted': sent, 'verification_required': True}
        raise RuntimeError('New-window automation is currently available only on macOS.')

    def wait_closed(self, handles, timeout=3):
        """Let windows close before the result is observed; an app may also ask to save first."""
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline and any(self.win32.user32.IsWindow(h) and self.win32.user32.IsWindowVisible(h) for h in handles):
            time.sleep(0.2)

    def press(self, action):
        raise RuntimeError('Pressing app controls is currently available only on macOS.')
