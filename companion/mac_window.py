"""Small AppKit touches for the companion's real macOS window, through the Objective-C
runtime (ctypes, no extra dependency). Every call is best-effort: on failure, or off macOS,
it returns False and the window stays an ordinary Qt window.
"""
import ctypes
import ctypes.util
import sys
import weakref

UTILITY_WINDOW = 1 << 4
NONACTIVATING_PANEL = 1 << 7  # takes typing without bringing A11y to the front (as Spotlight)
MINIATURIZABLE, RESIZABLE = 1 << 2, 1 << 3
TITLE_HIDDEN = 1
CLOSE_BUTTON, MINIATURIZE_BUTTON, ZOOM_BUTTON = 0, 1, 2
WINDOW_BELOW = -1
# On every Space (virtual desktop) and beside full-screen apps, out of Mission Control's shuffle.
ALL_SPACES, MOVE_TO_ACTIVE_SPACE, MANAGED, TRANSIENT, STATIONARY = 1 << 0, 1 << 1, 1 << 2, 1 << 3, 1 << 4
FULL_SCREEN_PRIMARY, FULL_SCREEN_AUXILIARY, FULL_SCREEN_NONE = 1 << 7, 1 << 8, 1 << 9

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


def prepare_window(widget, *, buttons=True, toggle_chat=None, minimize_owner=None, zoom=True):
    """Compact leading AppKit title and standard traffic lights; green toggles chat."""
    try:
        window = ns_window(widget)
        if not window:
            return False
        mask = send(window, 'styleMask', restype=ctypes.c_ulong)
        # Non-activating: showing her or a reply never brings A11y in front of the app a task is
        # typing into ("Input is unavailable", "the focus changed", live after she became a real window).
        send(window, 'setStyleMask:', (mask & ~UTILITY_WINDOW) | NONACTIVATING_PANEL | MINIATURIZABLE | RESIZABLE, restype=None, argtypes=(ctypes.c_ulong,))
        if send(window, 'respondsToSelector:', runtime().sel_registerName(b'setBecomesKeyOnlyIfNeeded:'),
                restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)):
            send(window, 'setBecomesKeyOnlyIfNeeded:', True, restype=None, argtypes=(ctypes.c_bool,))
        # She stays on screen when the user switches Spaces, instead of staying behind on the first one.
        behavior = send(window, 'collectionBehavior', restype=ctypes.c_ulong)
        behavior &= ~(MOVE_TO_ACTIVE_SPACE | MANAGED | TRANSIENT | FULL_SCREEN_PRIMARY | FULL_SCREEN_NONE)  # conflicting policies
        send(window, 'setCollectionBehavior:', behavior | ALL_SPACES | STATIONARY | FULL_SCREEN_AUXILIARY,
             restype=None, argtypes=(ctypes.c_ulong,))
        # A toolbar adds 9 pt on Tahoe and hides its proxy image while inactive.
        # A left title accessory keeps the ordinary titlebar and real window buttons.
        send(window, 'setToolbar:', None, restype=None, argtypes=(ctypes.c_void_p,))
        send(window, 'setTitleVisibility:', TITLE_HIDDEN, restype=None, argtypes=(ctypes.c_long,))
        send(window, 'setTitlebarSeparatorStyle:', 1, restype=None, argtypes=(ctypes.c_long,))  # none
        install_title(widget, window)
        for kind in (CLOSE_BUTTON, MINIATURIZE_BUTTON, ZOOM_BUTTON):
            button = send(window, 'standardWindowButton:', kind, argtypes=(ctypes.c_long,))
            if not button:
                continue
            send(button, 'setHidden:', not buttons, restype=None, argtypes=(ctypes.c_bool,))
            send(button, 'setEnabled:', zoom or kind != ZOOM_BUTTON, restype=None, argtypes=(ctypes.c_bool,))
            # Terminal's 14 pt lights: centres 16, 39, 62 pt from the left,
            # 16 pt below the outer top edge (Tahoe toolbar centres were 20 pt).
            container = send(button, 'superview')
            bounds = send(container, 'bounds', restype=Rect)
            if isinstance(bounds, Rect):
                send(button, 'setFrame:', rect(9+23*kind, bounds.size.height-23, 14, 14),
                     restype=None, argtypes=(Rect,))
            callback = toggle_chat if kind == ZOOM_BUTTON else minimize_owner if kind == MINIATURIZE_BUTTON else None
            if callback is not None:
                bind_window_button(widget, button, callback)
        return True
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return False


_button_target = None
_button_imp = None
_button_callbacks = {}


def weak_callback(callback):
    """Resolve Python and Qt bound methods without retaining their widget."""
    try:
        return weakref.WeakMethod(callback)
    except TypeError:
        owner, name = getattr(callback, '__self__', None), getattr(callback, '__name__', None)
        if owner is None or not name:
            return weakref.ref(callback)
        reference = weakref.ref(owner)
        def resolve():
            instance = reference()
            return getattr(instance, name, None) if instance is not None else None
        return resolve


def _dispatch_window_button(this, selector, sender):
    callback = _button_callbacks.get(sender)
    callback = callback() if callback else None
    if callback is not None:
        # Never unwind a Python exception through an Objective-C IMP.
        try:
            callback()
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Native window button failed')


def bind_window_button(widget, button, callback):
    """Keep the IMP/target alive; weak bound methods do not retain closed Qt windows."""
    global _button_target, _button_imp
    objc = runtime()
    if _button_target is None:
        objc.objc_allocateClassPair.restype = ctypes.c_void_p
        objc.objc_allocateClassPair.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t)
        objc.class_addMethod.restype = ctypes.c_bool
        objc.class_addMethod.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
        objc.objc_registerClassPair.restype = None
        objc.objc_registerClassPair.argtypes = (ctypes.c_void_p,)
        cls = objc.objc_getClass(b'A11yWindowButtonTarget')
        if not cls:
            cls = objc.objc_allocateClassPair(objc.objc_getClass(b'NSObject'), b'A11yWindowButtonTarget', 0)
            _button_imp = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(_dispatch_window_button)
            objc.class_addMethod(cls, objc.sel_registerName(b'perform:'), ctypes.cast(_button_imp, ctypes.c_void_p), b'v@:@')
            objc.objc_registerClassPair(cls)
        _button_target = send(send(cls, 'alloc'), 'init')
    _button_callbacks[button] = weak_callback(callback)
    widget.destroyed.connect(lambda *args, key=button: _button_callbacks.pop(key, None))
    send(button, 'setTarget:', _button_target, restype=None, argtypes=(ctypes.c_void_p,))
    send(button, 'setAction:', objc.sel_registerName(b'perform:'), restype=None, argtypes=(ctypes.c_void_p,))


def miniaturize(widget):
    """Minimise the parent; AppKit carries its attached child windows with it."""
    try:
        window = ns_window(widget)
        if not window:
            return False
        send(window, 'miniaturize:', None, restype=None, argtypes=(ctypes.c_void_p,))
        return True
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return False


def enable_buttons(widget, *, zoom=True):
    """Qt greys green out again whenever it updates a window it thinks can't be resized (her
    layout fixes her size); green opens and closes the input here, so it stays live."""
    try:
        window = ns_window(widget)
        if not window:
            return False
        for kind in (MINIATURIZE_BUTTON, ZOOM_BUTTON):
            button = send(window, 'standardWindowButton:', kind, argtypes=(ctypes.c_long,))
            if button:
                send(button, 'setEnabled:', zoom or kind != ZOOM_BUTTON, restype=None, argtypes=(ctypes.c_bool,))
        return True
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return False


def make_key(widget):
    """Give her window the keyboard after the user clicked her (a non-activating panel
    otherwise keeps typing in the app behind). Never called for showing her on her own."""
    try:
        window = ns_window(widget)
        if not window:
            return False
        send(window, 'makeKeyWindow', restype=None)
        return True
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return False


def release_key(widget):
    """Yield a non-activating panel's keyboard before acting in another app."""
    try:
        window = ns_window(widget)
        if not window:
            return False
        if send(window,'isKeyWindow',restype=ctypes.c_bool):
            send(window,'resignKeyWindow',restype=None)
        return True
    except (AttributeError,TypeError,ValueError,OSError,ctypes.ArgumentError):
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
        # Style-mask changes can order a Qt tool panel out. Explicitly order it back
        # beneath its owner, without activating either window or stealing task focus.
        number = send(above, 'windowNumber', restype=ctypes.c_long)
        send(below, 'orderWindow:relativeTo:', WINDOW_BELOW, number, restype=None,
             argtypes=(ctypes.c_long, ctypes.c_long))
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


class Point(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]


_menu_target = None
_menu_pick = None
_menu_choice = []


def _target():
    """One Objective-C object whose pick: records the chosen item's tag."""
    global _menu_target, _menu_pick
    if _menu_target is None:
        objc = runtime()
        objc.objc_allocateClassPair.restype = ctypes.c_void_p
        objc.objc_allocateClassPair.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t)
        objc.class_addMethod.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
        objc.objc_registerClassPair.argtypes = (ctypes.c_void_p,)
        name = b'A11yMenuTarget'
        cls = objc.objc_getClass(name)
        if not cls:
            cls = objc.objc_allocateClassPair(objc.objc_getClass(b'NSObject'), name, 0)

            def pick(this, selector, sender):
                _menu_choice.append(send(sender, 'tag', restype=ctypes.c_long))
            _menu_pick = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(pick)
            objc.class_addMethod(cls, objc.sel_registerName(b'pick:'), ctypes.cast(_menu_pick, ctypes.c_void_p), b'v@:@')
            objc.objc_registerClassPair(cls)
        _menu_target = send(send(cls, 'alloc'), 'init')
    return _menu_target


def ns_string(text):
    return send(runtime().objc_getClass(b'NSString'), 'stringWithUTF8String:', text.encode(), argtypes=(ctypes.c_char_p,))


def build_menu(entries, actions):
    """An NSMenu from entries: (title, action), (title, action, checked), (title, [entries])
    for a submenu, or None for a separator. actions collects the action per item tag."""
    ctypes.cdll.LoadLibrary('/System/Library/Frameworks/AppKit.framework/AppKit')
    item_class = runtime().objc_getClass(b'NSMenuItem')
    menu = send(send(runtime().objc_getClass(b'NSMenu'), 'alloc'), 'initWithTitle:', ns_string(''), argtypes=(ctypes.c_void_p,))
    for entry in entries:
        if entry is None:
            send(menu, 'addItem:', send(item_class, 'separatorItem'), restype=None, argtypes=(ctypes.c_void_p,))
            continue
        title, action = entry[0], entry[1]
        submenu = isinstance(action, list)
        item = send(send(item_class, 'alloc'), 'initWithTitle:action:keyEquivalent:', ns_string(title),
                    None if submenu else runtime().sel_registerName(b'pick:'), ns_string(''),
                    argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))
        if submenu:
            send(item, 'setSubmenu:', build_menu(action, actions), restype=None, argtypes=(ctypes.c_void_p,))
        else:
            send(item, 'setTarget:', _target(), restype=None, argtypes=(ctypes.c_void_p,))
            send(item, 'setTag:', len(actions), restype=None, argtypes=(ctypes.c_long,))
            actions.append(action)
            if len(entry) > 2 and entry[2]:
                send(item, 'setState:', 1, restype=None, argtypes=(ctypes.c_long,))
        send(menu, 'addItem:', item, restype=None, argtypes=(ctypes.c_void_p,))
    return menu


def popup_menu(entries, x, y, screen_height):
    """Show a real macOS menu at a Qt global point (top-left origin) and wait for it.
    Returns the chosen action, '' when dismissed, or None if it couldn't be shown."""
    try:
        if runtime() is None:
            return None
        actions = []
        menu = build_menu(entries, actions)
        _menu_choice.clear()
        send(menu, 'popUpMenuPositioningItem:atLocation:inView:', None, Point(x, screen_height-y), None,
             restype=ctypes.c_bool, argtypes=(ctypes.c_void_p, Point, ctypes.c_void_p))
        return actions[_menu_choice[-1]] if _menu_choice else ''
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError, IndexError):
        return None


def activate_app():
    """Activate only after the user asks to interact with her."""
    try:
        if runtime() is None:
            return False
        app = send(runtime().objc_getClass(b'NSApplication'), 'sharedApplication')
        send(app, 'activateIgnoringOtherApps:', True, restype=None, argtypes=(ctypes.c_bool,))
        return True
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return False


# NSRect is returned/passed by value on both supported macOS architectures.
class Size(ctypes.Structure):
    _fields_ = [('width', ctypes.c_double), ('height', ctypes.c_double)]


class Rect(ctypes.Structure):
    _fields_ = [('origin', Point), ('size', Size)]


def rect(x, y, width, height):
    return Rect(Point(x, y), Size(width, height))


_titles = {}
_title_target = None
_title_imp = None


def refresh_titles(*unused):
    # Notifications execute on AppKit's main thread, including for the child panel.
    for window, (_, label, icon) in list(_titles.items()):
        active = send(window, 'isKeyWindow', restype=ctypes.c_bool)
        color = send(runtime().objc_getClass(b'NSColor'),
                     'labelColor' if active else 'disabledControlTextColor')
        send(label, 'setTextColor:', color, restype=None, argtypes=(ctypes.c_void_p,))
        send(icon, 'setAlphaValue:', 1.0 if active else 0.45, restype=None,
             argtypes=(ctypes.c_double,))
        # Desaturate the inactive image without making it a template silhouette.
        filters = send(runtime().objc_getClass(b'NSArray'), 'array')
        if not active:
            filter_ = send(runtime().objc_getClass(b'CIFilter'), 'filterWithName:',
                           ns_string('CIColorControls'), argtypes=(ctypes.c_void_p,))
            zero = send(runtime().objc_getClass(b'NSNumber'), 'numberWithDouble:', 0.0,
                        argtypes=(ctypes.c_double,))
            send(filter_, 'setValue:forKey:', zero, ns_string('inputSaturation'), restype=None,
                 argtypes=(ctypes.c_void_p, ctypes.c_void_p))
            filters = send(runtime().objc_getClass(b'NSArray'), 'arrayWithObject:', filter_,
                           argtypes=(ctypes.c_void_p,))
        send(icon, 'setContentFilters:', filters, restype=None, argtypes=(ctypes.c_void_p,))


def _title_notification(this, selector, notification):
    try:
        refresh_titles()
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Native title refresh failed')


def install_title(widget, window):
    """Public AppKit accessory: 30 pt title interior plus the 1 pt outer rim.

    NSImageView has no proxy URL, target, action or drag source. The ordinary
    NSWindow title remains available to accessibility and the Window menu.
    """
    global _title_target, _title_imp
    if window in _titles:
        return
    objc = runtime()
    ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreImage.framework/CoreImage')
    accessory = send(send(objc.objc_getClass(b'NSTitlebarAccessoryViewController'), 'alloc'), 'init')
    view = send(send(objc.objc_getClass(b'NSView'), 'alloc'), 'initWithFrame:', rect(0, 0, max(1, widget.width()-90), 30), argtypes=(Rect,))
    icon = send(send(objc.objc_getClass(b'NSImageView'), 'alloc'), 'initWithFrame:', rect(3, 8, 16, 16), argtypes=(Rect,))
    label = send(objc.objc_getClass(b'NSTextField'), 'labelWithString:', ns_string(widget.windowTitle()), argtypes=(ctypes.c_void_p,))
    send(label, 'setFrame:', rect(0, 5, max(1, widget.width()-90), 20), restype=None, argtypes=(Rect,))
    font = send(objc.objc_getClass(b'NSFont'), 'boldSystemFontOfSize:', 13.0, argtypes=(ctypes.c_double,))
    send(label, 'setAutoresizingMask:', 2, restype=None, argtypes=(ctypes.c_ulong,))
    send(label, 'setFont:', font, restype=None, argtypes=(ctypes.c_void_p,))
    send(view, 'addSubview:', icon, restype=None, argtypes=(ctypes.c_void_p,))
    send(view, 'addSubview:', label, restype=None, argtypes=(ctypes.c_void_p,))
    send(accessory, 'setView:', view, restype=None, argtypes=(ctypes.c_void_p,))
    send(accessory, 'setLayoutAttribute:', 1, restype=None, argtypes=(ctypes.c_long,))  # left, after buttons
    send(window, 'addTitlebarAccessoryViewController:', accessory, restype=None, argtypes=(ctypes.c_void_p,))
    # Terminal's one-device-pixel black rule under the title bar. It sits in the frame view above
    # the content, because AppKit draws a light edge over the content's first row.
    content = send(window, 'contentView')
    frame_view = send(content, 'superview')
    top = send(content, 'frame', restype=Rect)
    if frame_view and isinstance(top, Rect):
        scale = send(window, 'backingScaleFactor', restype=ctypes.c_double) or 1.0
        rule = send(send(objc.objc_getClass(b'NSBox'), 'alloc'), 'initWithFrame:',
                    rect(0, top.origin.y+top.size.height-1/scale, top.size.width, 1/scale), argtypes=(Rect,))
        send(rule, 'setBoxType:', 4, restype=None, argtypes=(ctypes.c_long,))  # custom
        send(rule, 'setBorderType:', 0, restype=None, argtypes=(ctypes.c_long,))
        send(rule, 'setFillColor:', send(objc.objc_getClass(b'NSColor'), 'blackColor'),
             restype=None, argtypes=(ctypes.c_void_p,))
        send(rule, 'setAutoresizingMask:', 2 | 8, restype=None, argtypes=(ctypes.c_ulong,))  # width, stays at top
        send(frame_view, 'addSubview:positioned:relativeTo:', rule, 1, None,
             restype=None, argtypes=(ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p))
        send(rule, 'release', restype=None)
    _titles[window] = (accessory, label, icon)
    def update(text):
        send(label, 'setStringValue:', ns_string(text), restype=None, argtypes=(ctypes.c_void_p,))
    widget.windowTitleChanged.connect(update)
    def cleanup(*unused):
        _titles.pop(window, None)
    widget.destroyed.connect(cleanup)
    if _title_target is None:
        objc.objc_allocateClassPair.restype = ctypes.c_void_p
        objc.objc_allocateClassPair.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t)
        objc.class_addMethod.restype = ctypes.c_bool
        objc.class_addMethod.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
        objc.objc_registerClassPair.argtypes = (ctypes.c_void_p,)
        cls = objc.objc_allocateClassPair(objc.objc_getClass(b'NSObject'), b'A11yTitleObserver', 0)
        _title_imp = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(_title_notification)
        objc.class_addMethod(cls, objc.sel_registerName(b'changed:'), ctypes.cast(_title_imp, ctypes.c_void_p), b'v@:@')
        objc.objc_registerClassPair(cls)
        _title_target = send(send(cls, 'alloc'), 'init')
        center = send(objc.objc_getClass(b'NSNotificationCenter'), 'defaultCenter')
        for name in ('NSWindowDidBecomeKeyNotification', 'NSWindowDidResignKeyNotification'):
            send(center, 'addObserver:selector:name:object:', _title_target, objc.sel_registerName(b'changed:'),
                 ns_string(name), None, restype=None, argtypes=(ctypes.c_void_p,)*4)
    for item in (icon, view, accessory):
        send(item, 'release', restype=None)
    refresh_titles()


def resize_title(widget):
    """Keep a growing reply accessory within the titlebar's available width."""
    try:
        window = ns_window(widget)
        if window not in _titles:
            return False
        view = send(_titles[window][0], 'view')
        send(view, 'setFrameSize:', Size(max(1, widget.width()-90), 30), restype=None, argtypes=(Size,))
        return True
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return False


def set_proxy_icon(widget, path, png):
    """Permanent image accessory, never a draggable document proxy."""
    try:
        window = ns_window(widget)
        if not window or window not in _titles:
            return False
        data = send(runtime().objc_getClass(b'NSData'), 'dataWithBytes:length:', png, len(png),
                    argtypes=(ctypes.c_char_p, ctypes.c_ulong))
        image = send(send(runtime().objc_getClass(b'NSImage'), 'alloc'), 'initWithData:', data, argtypes=(ctypes.c_void_p,))
        if not image:
            return False
        send(_titles[window][2], 'setImage:', image, restype=None, argtypes=(ctypes.c_void_p,))
        send(_titles[window][1], 'setFrame:', rect(19, 5, max(1, widget.width()-109), 20),
             restype=None, argtypes=(Rect,))
        send(image, 'release', restype=None)
        refresh_titles()
        return True
    except (AttributeError, TypeError, ValueError, OSError, ctypes.ArgumentError):
        return False
