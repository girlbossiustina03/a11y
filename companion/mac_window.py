"""Small AppKit touches for the companion's real macOS window, through the Objective-C
runtime (ctypes, no extra dependency). Every call is best-effort: on failure, or off macOS,
it returns False and the window stays an ordinary Qt window.
"""
import ctypes
import ctypes.util
import sys

UTILITY_WINDOW = 1 << 4
TITLE_HIDDEN = 1
CLOSE_BUTTON, MINIATURIZE_BUTTON, ZOOM_BUTTON = 0, 1, 2
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


def prepare_window(widget, *, buttons=True):
    """A real title bar like Terminal's. With buttons, yellow and green are turned off (she
    can't be minimised or zoomed); without, the title bar is a plain strip (the reply)."""
    try:
        window = ns_window(widget)
        if not window:
            return False
        mask = send(window, 'styleMask', restype=ctypes.c_ulong)
        send(window, 'setStyleMask:', mask & ~UTILITY_WINDOW, restype=None, argtypes=(ctypes.c_ulong,))
        for kind in (CLOSE_BUTTON, MINIATURIZE_BUTTON, ZOOM_BUTTON):
            button = send(window, 'standardWindowButton:', kind, argtypes=(ctypes.c_long,))
            if not button:
                continue
            if not buttons:
                send(button, 'setHidden:', True, restype=None, argtypes=(ctypes.c_bool,))
            elif kind != CLOSE_BUTTON:
                send(button, 'setEnabled:', False, restype=None, argtypes=(ctypes.c_bool,))
        if not buttons:
            send(window, 'setTitleVisibility:', TITLE_HIDDEN, restype=None, argtypes=(ctypes.c_long,))
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


def to_srgb(red, green, blue, space):
    """Terminal stores colours in calibrated (generic) RGB (space 1) or device RGB (2); the
    same numbers read as sRGB look darker. Convert through AppKit; None if unavailable."""
    try:
        if runtime() is None:
            return None
        ctypes.cdll.LoadLibrary('/System/Library/Frameworks/AppKit.framework/AppKit')
        color_class = runtime().objc_getClass(b'NSColor')
        maker = 'colorWithCalibratedRed:green:blue:alpha:' if space == 1 else 'colorWithDeviceRed:green:blue:alpha:'
        color = send(color_class, maker, red, green, blue, 1.0, argtypes=(ctypes.c_double,)*4)
        srgb = send(runtime().objc_getClass(b'NSColorSpace'), 'sRGBColorSpace')
        converted = send(color, 'colorUsingColorSpace:', srgb, argtypes=(ctypes.c_void_p,))
        if not converted:
            return None
        return tuple(send(converted, name, restype=ctypes.c_double) for name in ('redComponent', 'greenComponent', 'blueComponent'))
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return None


def set_blur(widget, radius):
    """Blur what's behind the window, as Terminal does for its active windows (a private
    but long-standing WindowServer call, the one Terminal and iTerm use)."""
    try:
        window = ns_window(widget)
        if not window:
            return False
        number = send(window, 'windowNumber', restype=ctypes.c_long)
        graphics = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        graphics.CGSMainConnectionID.restype = ctypes.c_int
        graphics.CGSSetWindowBackgroundBlurRadius.argtypes = (ctypes.c_int, ctypes.c_long, ctypes.c_int)
        return graphics.CGSSetWindowBackgroundBlurRadius(graphics.CGSMainConnectionID(), number, int(radius)) == 0
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return False
