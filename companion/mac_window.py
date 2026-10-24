"""Small AppKit touches for the companion's real macOS window, through the Objective-C
runtime (ctypes, no extra dependency). Every call is best-effort: on failure, or off macOS,
it returns False and the window stays an ordinary Qt window.
"""
import ctypes
import ctypes.util
import sys

FULL_SIZE_CONTENT_VIEW = 1 << 15
UTILITY_WINDOW = 1 << 4
TITLE_HIDDEN = 1
MINIATURIZE_BUTTON, ZOOM_BUTTON = 1, 2
WINDOW_BELOW = -1

_objc = None


def runtime():
    global _objc
    if _objc is None and sys.platform == 'darwin':
        try:
            _objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
            _objc.objc_getClass.restype = ctypes.c_void_p
            _objc.objc_getClass.argtypes = [ctypes.c_char_p]
            _objc.sel_registerName.restype = ctypes.c_void_p
            _objc.sel_registerName.argtypes = [ctypes.c_char_p]
        except (OSError, AttributeError, TypeError):
            _objc = False
    return _objc or None


def send(receiver, selector, *args, restype=ctypes.c_void_p, argtypes=()):
    """objc_msgSend with an exact prototype (required on arm64)."""
    objc = runtime()
    function = ctypes.cast(objc.objc_msgSend, ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
    return function(receiver, objc.sel_registerName(selector.encode()), *args)


def ns_window(widget):
    """The NSWindow behind a shown top-level Qt widget, or None."""
    if runtime() is None:
        return None
    view = int(widget.winId())
    return send(view, 'window') if view else None


def style_titlebar(widget, red, green, blue, alpha=1.0):
    """Real title bar and traffic lights, drawn over the window's own background: the bar
    is transparent and the content runs underneath it, so the window's colour (the
    terminal theme) shows through. Yellow and green are turned off; she can't be minimised
    or zoomed. Returns True when applied."""
    try:
        window = ns_window(widget)
        if not window:
            return False
        mask = send(window, 'styleMask', restype=ctypes.c_ulong)
        send(window, 'setStyleMask:', (mask | FULL_SIZE_CONTENT_VIEW) & ~UTILITY_WINDOW,
             restype=None, argtypes=(ctypes.c_ulong,))
        send(window, 'setTitlebarAppearsTransparent:', True, restype=None, argtypes=(ctypes.c_bool,))
        send(window, 'setTitleVisibility:', TITLE_HIDDEN, restype=None, argtypes=(ctypes.c_long,))
        send(window, 'setMovableByWindowBackground:', False, restype=None, argtypes=(ctypes.c_bool,))
        color = send(runtime().objc_getClass(b'NSColor'), 'colorWithSRGBRed:green:blue:alpha:',
                     red, green, blue, alpha, argtypes=(ctypes.c_double,)*4)
        send(window, 'setBackgroundColor:', color, restype=None, argtypes=(ctypes.c_void_p,))
        for kind in (MINIATURIZE_BUTTON, ZOOM_BUTTON):
            button = send(window, 'standardWindowButton:', kind, argtypes=(ctypes.c_long,))
            if button:
                send(button, 'setEnabled:', False, restype=None, argtypes=(ctypes.c_bool,))
        return True
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return False


def keep_below(parent, child):
    """Attach child's window to parent's, ordered below it: it moves with her and never
    comes in front, even when clicked."""
    try:
        above, below = ns_window(parent), ns_window(child)
        if not (above and below):
            return False
        send(above, 'addChildWindow:ordered:', below, WINDOW_BELOW, restype=None,
             argtypes=(ctypes.c_void_p, ctypes.c_long))
        return True
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return False


def detach(parent, child):
    try:
        above, below = ns_window(parent), ns_window(child)
        if above and below:
            send(above, 'removeChildWindow:', below, restype=None, argtypes=(ctypes.c_void_p,))
            return True
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        pass
    return False


def titlebar_height(widget):
    """Height of the real title bar in points (28 on current macOS), or None."""
    try:
        window = ns_window(widget)
        if not window:
            return None

        class Rect(ctypes.Structure):
            _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double), ('w', ctypes.c_double), ('h', ctypes.c_double)]
        frame = send(window, 'frame', restype=Rect)
        layout = send(window, 'contentLayoutRect', restype=Rect)
        return round(frame.h-layout.h)
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return None
