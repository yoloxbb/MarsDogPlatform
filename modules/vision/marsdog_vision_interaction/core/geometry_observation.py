"""Geometry provenance for a single camera inference; no depth or TF ownership."""
import math


def frame_geometry(humans, candidates, width, height, *, stereo_split=False):
    """Use only tracks matched uniquely to this frame's unrounded detections.

    Tracker boxes are rounded to four decimals. Retained tracks, ambiguous
    matches and cropped stereo views cannot prove an original-image ROI.
    """
    if stereo_split or width <= 0 or height <= 0:
        return {}
    boxes = []
    for human in humans:
        try:
            box = [float(human[k]) for k in ('x', 'y', 'w', 'h')]
        except (KeyError, TypeError, ValueError):
            continue
        x, y, w, h = box
        if (not all(math.isfinite(v) for v in box) or min(x, y) < 0
                or min(w, h) <= 0 or x+w > 1.0001 or y+h > 1.0001):
            continue
        boxes.append(box)
    matches = {}
    for candidate in candidates:
        if candidate.get('tracking_state') != 'tracking':
            continue
        box = candidate.get('bbox', [])
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        found = [i for i, raw in enumerate(boxes)
                 if all(abs(a-float(b)) <= .000051 for a, b in zip(raw, box))]
        if len(found) == 1:
            matches[candidate['target_id']] = found[0]
    result = {}
    for target, index in matches.items():
        if list(matches.values()).count(index) != 1:
            continue
        x, y, w, h = boxes[index]
        left, top = math.floor(x*width+1e-7), math.floor(y*height+1e-7)
        right, bottom = min(width, math.ceil((x+w)*width-1e-7)), min(height, math.ceil((y+h)*height-1e-7))
        if right > left and bottom > top:
            result[target] = {'x_offset': left, 'y_offset': top,
                              'width': right-left, 'height': bottom-top}
    return result
