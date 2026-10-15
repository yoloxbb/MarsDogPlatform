"""ROS-independent original-image geometry boundary validation."""
import math


def geometry_request(payload, target_id):
    """Validate original-image provenance before constructing any ROS request."""
    if (not isinstance(payload, dict) or payload.get('ok') is not True
            or payload.get('target_id') != target_id
            or payload.get('coordinate_space') != 'original_image_pixels'):
        raise ValueError('geometry_target_or_coordinate_mismatch')
    header = payload.get('image_header', {})
    stamp = header.get('stamp')
    frame = header.get('frame_id')
    if (isinstance(stamp, bool) or not isinstance(stamp, (int, float))
            or not math.isfinite(stamp) or not 0 < stamp < 2**31
            or not isinstance(frame, str) or not frame.strip()):
        raise ValueError('geometry_original_header_required')
    dimensions = [payload.get('image_width'), payload.get('image_height')]
    roi = payload.get('bbox', {})
    keys = ('x_offset', 'y_offset', 'width', 'height')
    values = [roi.get(k) for k in keys] if isinstance(roi, dict) else []
    if len(values) != 4 or any(type(v) is not int or v < 0 for v in dimensions+values):
        raise ValueError('geometry_invalid_roi')
    width, height = dimensions
    x, y, w, h = values
    if not (0 < width <= 16384 and 0 < height <= 16384 and w > 0 and h > 0
            and x+w <= width and y+h <= height):
        raise ValueError('geometry_roi_outside_original_image')
    sec, ns = divmod(round(stamp*1_000_000_000), 1_000_000_000)
    return {'sec': sec, 'nanosec': ns, 'frame_id': frame}, dict(zip(keys, values))
