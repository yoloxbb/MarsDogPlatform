"""Coordinate/input conversion only; no motion decisions or controller gains."""
import math
import statistics
import struct


def rotate(q, xyz):
    x, y, z, w = q
    vx, vy, vz = xyz
    tx, ty, tz = 2*(y*vz-z*vy), 2*(z*vx-x*vz), 2*(x*vy-y*vx)
    return (vx+w*tx+y*tz-z*ty, vy+w*ty+z*tx-x*tz, vz+w*tz+x*ty-y*tx)


def transform_point(transform, xyz):
    q, t = transform.rotation, transform.translation
    p = rotate((q.x, q.y, q.z, q.w), xyz)
    return p[0]+t.x, p[1]+t.y, p[2]+t.z


def bbox_point(bbox, image, intrinsics, radius=2):
    """Normalized xywh + registered depth -> optical XYZ, in metres.

    Only depth representation/geometry are checked. No confidence, minimum
    distance, arrival or motion guard is introduced here.
    """
    x, y, width, height = map(float, bbox)
    if not all(math.isfinite(v) for v in (x, y, width, height)) or width <= 0 or height <= 0:
        raise ValueError('bbox must contain finite normalized xywh')
    u = int(round((x+width/2)*(image.width-1)))
    v = int(round((y+height/2)*(image.height-1)))
    if not (0 <= u < image.width and 0 <= v < image.height):
        raise ValueError('bbox centre outside registered depth image')
    fx, fy, cx, cy = intrinsics.k[0], intrinsics.k[4], intrinsics.k[2], intrinsics.k[5]
    if not all(math.isfinite(n) for n in (fx, fy, cx, cy)) or fx <= 0 or fy <= 0:
        raise ValueError('camera intrinsics unavailable')
    if image.encoding in ('16UC1', 'mono16'):
        code, size, scale = 'H', 2, .001
    elif image.encoding == '32FC1':
        code, size, scale = 'f', 4, 1.
    else:
        raise ValueError('depth encoding must be 16UC1 or 32FC1')
    samples = []
    for row in range(max(0, v-radius), min(image.height, v+radius+1)):
        for col in range(max(0, u-radius), min(image.width, u+radius+1)):
            z = struct.unpack_from(('>' if image.is_bigendian else '<')+code,
                                   image.data, row*image.step+col*size)[0]*scale
            if math.isfinite(z) and z > 0:
                samples.append(z)
    if not samples:
        raise ValueError('bbox has no valid depth')
    z = statistics.median(samples)
    return (u-cx)*z/fx, (v-cy)*z/fy, z
