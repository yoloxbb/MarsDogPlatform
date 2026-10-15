"""Depth representation and pinhole geometry; no ROS or hardware required."""
import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace as NS
import pytest

spec = importlib.util.spec_from_file_location('target_geometry',
    Path(__file__).parents[1]/'robot_local_motion/target_geometry.py')
geometry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geometry)


@pytest.mark.parametrize('encoding,endian,scale', [('16UC1', False, 1000), ('16UC1', True, 1000), ('32FC1', False, 1)])
def test_registered_depth_row_padding_units_and_off_axis_point(encoding, endian, scale):
    code, size = ('H', 2) if encoding == '16UC1' else ('f', 4)
    row = struct.pack(('>' if endian else '<')+code*5, *[int(2*scale) if size == 2 else 2.]*5)+b'pad!'
    image = NS(width=5, height=5, encoding=encoding, is_bigendian=endian, step=len(row), data=row*5)
    info = NS(k=[4., 0., 2., 0., 4., 2., 0., 0., 1.])
    assert geometry.bbox_point([.65, .15, .2, .2], image, info) == pytest.approx((.5, -.5, 2.))


def test_optical_axis_maps_to_robot_forward_with_extrinsic_translation():
    tf = NS(rotation=NS(x=-.5, y=.5, z=-.5, w=.5), translation=NS(x=.2, y=0., z=.4))
    assert geometry.transform_point(tf, (0., 0., 2.)) == pytest.approx((2.2, 0., .4))
