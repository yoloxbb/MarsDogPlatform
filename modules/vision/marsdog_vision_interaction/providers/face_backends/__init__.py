"""Format-selected YuNet and SFace backends.

The public factory functions in this module keep the providers independent of
the model runtime.  A model's suffix is the only routing switch: OpenCV is
used for ONNX files and RKNN Lite is used for the verified RKNN artifacts.
"""

from .factory import (
    FaceBackendError,
    OpenCVFaceDetector,
    OpenCVSFaceRecognizer,
    RKNN_PROFILES,
    RKNNSFaceRecognizer,
    RKNNYuNetDetector,
    SFACE_FP16_SHA256,
    SFACE_PROFILE,
    YUNET_FP16_SHA256,
    YUNET_PROFILE,
    create_face_detector,
    create_face_recognizer,
    decode_yunet,
    decode_yunet_outputs,
)

__all__ = [
    "FaceBackendError",
    "OpenCVFaceDetector",
    "OpenCVSFaceRecognizer",
    "RKNN_PROFILES",
    "RKNNYuNetDetector",
    "RKNNSFaceRecognizer",
    "SFACE_FP16_SHA256",
    "SFACE_PROFILE",
    "YUNET_FP16_SHA256",
    "YUNET_PROFILE",
    "create_face_detector",
    "create_face_recognizer",
    "decode_yunet",
    "decode_yunet_outputs",
]
