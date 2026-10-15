"""Bounded C5 decoder for the existing 115200 UWB wire format (no SDK state)."""
import binascii
from collections import Counter
from dataclasses import dataclass
import struct


BODY = struct.Struct('<IIIHfffB6b4bB')


@dataclass(frozen=True)
class UwbFrame:
    wire_sequence: int
    sync_count: int
    index: int
    fob_id: int
    fob_type: int
    distance: float
    angle_deg: float
    pitch_deg: float
    rssi_length: int
    rssi: tuple
    rx_power: int
    rssi_fpp: int
    rssi_np: int
    rssi_ble: int
    confidence: int
    declared_length: int


def canonical_id(value):
    """Accept uint32 decimal/hex IDs; use one spelling in observations and goals."""
    if isinstance(value, bool):
        raise ValueError('beacon ID must be uint32')
    text = str(value).strip()
    number = int(text, 16 if text.lower().startswith('0x') else 10)
    if not 0 <= number <= 0xffffffff:
        raise ValueError('beacon ID must be uint32')
    return f'0x{number:08x}'


class C5Decoder:
    def __init__(self, allow_observed_len33=False, partial_timeout_sec=0.2):
        self.allow_observed_len33 = allow_observed_len33
        self.partial_timeout_sec = partial_timeout_sec
        self.buffer = bytearray()
        self.last_feed = None
        self.counters = Counter()

    def reset(self):
        self.buffer.clear()
        self.last_feed = None

    def feed(self, data, now):
        if self.last_feed is not None and (now < self.last_feed or
                now - self.last_feed > self.partial_timeout_sec):
            if self.buffer:
                self.counters['partial_timeout'] += 1
            self.reset()
        self.last_feed = now
        self.counters['bytes'] += len(data)
        self.buffer.extend(data)
        if len(self.buffer) > 8192:
            self.counters['buffer_overflow'] += 1
            del self.buffer[:-4096]
        result = []
        while len(self.buffer) >= 5:
            head = self.buffer.find(b'\x55\xaa')
            if head < 0:
                self.counters['noise_bytes'] += len(self.buffer) - 1
                del self.buffer[:-1]
                break
            if head:
                self.counters['noise_bytes'] += head
                del self.buffer[:head]
            if len(self.buffer) < 5:
                break
            length = int.from_bytes(self.buffer[3:5], 'little')
            if not 2 <= length <= 98:
                self.counters['bad_outer_length'] += 1
                del self.buffer[0]
                continue
            total = length + 7
            if len(self.buffer) < total:
                break
            packet = bytes(self.buffer[:total])
            payload = packet[5:-2]
            if binascii.crc_hqx(payload, 0) != int.from_bytes(packet[-2:], 'big'):
                self.counters['crc_error'] += 1
                del self.buffer[0]
                continue
            del self.buffer[:total]
            self.counters['crc_valid'] += 1
            if payload[0] != 0xc5:
                self.counters['other_packet_type'] += 1
                continue
            # Exact observed variant only. Do not generally ignore the inner size.
            variant = len(payload) == 40 and payload[1] == 33
            standard = len(payload) == 40 and payload[1] == BODY.size
            if not (standard or (variant and self.allow_observed_len33)):
                self.counters['unsupported_c5_length'] += 1
                continue
            if variant:
                self.counters['observed_len33'] += 1
            v = BODY.unpack_from(payload, 2)
            result.append(UwbFrame(packet[2], *v[:8], tuple(v[8:14]), *v[14:], payload[1]))
            self.counters['decoded_c5'] += 1
        return result
