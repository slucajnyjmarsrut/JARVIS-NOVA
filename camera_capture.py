"""Single-frame camera capture in RAM; release hardware even on errors.

Never calls cv2.imwrite/VideoWriter. Does not open a preview window.
Only the authorized pipeline calls capture_jpeg().
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import sys


class CameraError(RuntimeError):
    pass


@dataclass(frozen=True)
class CameraConfig:
    device_index: int = 0
    max_width: int = 1280
    max_height: int = 720
    jpeg_quality: int = 80
    warmup_frames: int = 3


class CameraFrameSource:
    def __init__(self, config: CameraConfig = CameraConfig(), *, cv2_module=None):
        if not 0 <= config.device_index <= 20:
            raise ValueError("Camera index must be 0–20")
        if not 128 <= config.max_width <= 4096 or not 128 <= config.max_height <= 4096:
            raise ValueError("Image resolution out of bounds")
        if not 30 <= config.jpeg_quality <= 95:
            raise ValueError("JPEG quality out of bounds")
        if not 0 <= config.warmup_frames <= 10:
            raise ValueError("Camera warmup must be 0–10 frames")
        self.config = config
        self._cv2 = cv2_module

    def capture_jpeg(self) -> bytes:
        try:
            if self._cv2 is None:
                import cv2
            else:
                cv2 = self._cv2
        except ImportError as exc:
            raise CameraError("OpenCV is required for camera capture") from exc

        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        camera = cv2.VideoCapture(self.config.device_index, backend)
        # DirectShow is often suitable on Windows, but not every webcam supports it.
        # Fall back to OpenCV's automatic backend before declaring the camera broken.
        if sys.platform == "win32" and not camera.isOpened():
            camera.release()
            camera = cv2.VideoCapture(self.config.device_index, cv2.CAP_ANY)
        try:
            if not camera.isOpened():
                raise CameraError("Camera did not open. Check Windows camera privacy permission.")
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.max_width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.max_height)
            frame = None
            for _ in range(self.config.warmup_frames + 1):
                ok, frame = camera.read()
                if not ok or frame is None:
                    raise CameraError("Camera returned no frame")
            height, width = frame.shape[:2]
            if width < 1 or height < 1:
                raise CameraError("Invalid camera frame dimensions")
            ratio = min(1.0, self.config.max_width / width, self.config.max_height / height)
            if ratio < 1.0:
                frame = cv2.resize(frame, (max(1, round(width*ratio)),
                                           max(1, round(height*ratio))), interpolation=cv2.INTER_AREA)
            ok, jpeg = cv2.imencode(".jpg", frame,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), self.config.jpeg_quality])
            if not ok or jpeg is None:
                raise CameraError("JPEG compression failed")
            result = jpeg.tobytes()
            if not result.startswith(b"\xff\xd8\xff") or not result.endswith(b"\xff\xd9"):
                raise CameraError("Incomplete JPEG from camera")
            if len(result) > 4_000_000:
                raise CameraError("Camera JPEG unexpectedly large")
            return result
        finally:
            # Hardware resource must always be released even on exception.
            camera.release()
