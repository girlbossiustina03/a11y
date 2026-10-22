"""Windows.Media.Ocr text regions for one in-memory frame.

Uses the OCR engine built into Windows 10/11 through the pywinrt projection
packages (optional dependencies). Returns None when they or a recognizer for the
user's languages are unavailable, so the task falls back to image analysis.
Recognized text is returned to the caller only; nothing is stored."""
import threading

_engine = None
_lock = threading.Lock()


def _ocr_engine():
    global _engine
    with _lock:
        if _engine is None:
            from winrt.windows.media.ocr import OcrEngine
            _engine = OcrEngine.try_create_from_user_profile_languages() or False
        return _engine or None


def regions_from_lines(lines, width, height, limit=200):
    """[(text, [(x, y, w, h) word rects in pixels])] → normalized line rectangles."""
    result = []
    for text, words in lines:
        text = (text or '').strip()
        if not text or not words:
            continue
        left = min(x for x, _, _, _ in words)
        top = min(y for _, y, _, _ in words)
        right = max(x+w for x, _, w, _ in words)
        bottom = max(y+h for _, y, _, h in words)
        if right <= left or bottom <= top:
            continue
        result.append({'text': text[:160], 'x': round(left/width, 4), 'y': round(top/height, 4),
                       'width': round((right-left)/width, 4), 'height': round((bottom-top)/height, 4)})
        if len(result) >= limit:
            break
    return result


def recognize(bgra, width, height):
    try:
        import asyncio
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter
        engine = _ocr_engine()
        if engine is None:
            return None
        writer = DataWriter()
        writer.write_bytes(bytes(bgra))
        bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8, width, height)

        async def run():
            return await engine.recognize_async(bitmap)
        result = asyncio.run(run())
        lines = []
        for line in result.lines:
            words = [(word.bounding_rect.x, word.bounding_rect.y, word.bounding_rect.width, word.bounding_rect.height)
                     for word in line.words]
            lines.append((line.text, words))
        return regions_from_lines(lines, width, height)
    except Exception:  # ImportError, missing language packs, WinRT errors
        return None
