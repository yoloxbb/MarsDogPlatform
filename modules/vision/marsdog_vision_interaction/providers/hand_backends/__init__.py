"""Format-selected hand landmark backends.

The public contract deliberately stays smaller than either MediaPipe Tasks or
RKNN Lite.  Both adapters return the same full precision, frame-normalized
landmarks so gesture code does not need to know which model produced them.
"""

from .base import HandBackendError, HandResult
from .factory import create_hand_backend

__all__ = ["HandBackendError", "HandResult", "create_hand_backend"]
