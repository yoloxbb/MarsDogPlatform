import binascii
import local_motion_test_support
from _local_motion_under_test.uwb_protocol import BODY, C5Decoder, UwbFrame, canonical_id
from _local_motion_under_test.uwb_tracking import BeaconTracker, TrackingConfig
from _local_motion_under_test.guard import ObservationOrder


def packet(identity=0x87654322, sync=1, distance=2.0, angle=0.0, declared=33):
    body = BODY.pack(sync, 0, identity, 1, distance, angle, 0.0, 6, *([0] * 11))
    payload = bytes([0xc5, declared]) + body
    return b'\x55\xaa\x01' + len(payload).to_bytes(2, 'little') + payload + binascii.crc_hqx(payload, 0).to_bytes(2, 'big')


def frame(**kwargs):
    return C5Decoder(True).feed(packet(**kwargs), 0)[0]
