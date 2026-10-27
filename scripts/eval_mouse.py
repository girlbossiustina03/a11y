"""Owner-only live-test mouse stimulus; never used by the model or app executor."""
import ctypes as C
import time


class Point(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double)]


def right_click(pid, x, y, *, libraries=None):
    if libraries is None:
        libraries = [C.CDLL('/System/Library/Frameworks/'+name+'.framework/'+name)
                     for name in ('ApplicationServices','CoreGraphics','CoreFoundation')]
    ax, cg, cf = libraries
    def bind(lib, name, result, arguments):
        fn = getattr(lib, name); fn.restype = result; fn.argtypes = arguments
        return fn
    system = bind(ax,'AXUIElementCreateSystemWide',C.c_void_p,[])()
    hit = C.c_void_p()
    events = []
    release = bind(cf,'CFRelease',None,[C.c_void_p])
    try:
        status = bind(ax,'AXUIElementCopyElementAtPosition',C.c_int,[C.c_void_p,C.c_float,C.c_float,C.POINTER(C.c_void_p)])(system,x,y,C.byref(hit))
        owner = C.c_int()
        if status or not hit or bind(ax,'AXUIElementGetPid',C.c_int,[C.c_void_p,C.POINTER(C.c_int)])(hit,C.byref(owner)) or owner.value != pid:
            raise RuntimeError('Test click no longer points at the owned companion.')
        create = bind(cg,'CGEventCreateMouseEvent',C.c_void_p,[C.c_void_p,C.c_uint32,Point,C.c_uint32])
        post = bind(cg,'CGEventPost',None,[C.c_uint32,C.c_void_p])
        events = [create(None,kind,Point(x,y),1) for kind in (3,4)]  # real right down/up, never AXPress
        if not all(events):
            raise RuntimeError('Could not create the test mouse events.')
        post(0,events[0])
        try:
            time.sleep(.03)
        finally:
            post(0,events[1])
    finally:
        for value in [*events,hit,system]:
            if value:
                release(value)
