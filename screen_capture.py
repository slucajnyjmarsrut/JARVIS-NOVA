"""In-memory screen JPEG capture for local vision, gated by the caller's consent.

Windows screen sharing authorization is controlled by the JARVIS GUI. This module
never sends images, writes files, or makes network requests.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any


class ScreenCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScreenConfig:
    max_width: int = 1280
    max_height: int = 720
    quality: int = 80


class ScreenFrameSource:
    def __init__(self, config: ScreenConfig = ScreenConfig(), *, grab: Any = None):
        if not 128 <= config.max_width <= 4096 or not 128 <= config.max_height <= 4096:
            raise ValueError('Screen resolution out of bounds')
        if not 30 <= config.quality <= 95:
            raise ValueError('JPEG quality out of bounds')
        self.config = config
        self._grab = grab

    def capture_jpeg(self) -> bytes:
        if self._grab is None:
            from PIL import ImageGrab
            grab = ImageGrab.grab
        else:
            grab = self._grab
        try:
            image = grab()
            if image is None:
                raise ScreenCaptureError('No screen captured')
            # Work on a copy: do not mutate any image object supplied by caller.
            image = image.convert('RGB')
            image.thumbnail((self.config.max_width, self.config.max_height))
            stream = BytesIO()
            image.save(stream, format='JPEG', quality=self.config.quality)
            jpeg = stream.getvalue()
            if len(jpeg) > 4_000_000 or not jpeg.startswith(b'\xff\xd8\xff') or not jpeg.endswith(b'\xff\xd9'):
                raise ScreenCaptureError('Invalid or oversized screen JPEG')
            return jpeg
        except ScreenCaptureError:
            raise
        except Exception as exc:
            raise ScreenCaptureError(f'Cannot capture screen: {exc}') from exc
