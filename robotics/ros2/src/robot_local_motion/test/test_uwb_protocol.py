import pytest
from uwb_test_support import C5Decoder, canonical_id, packet


def test_exact_legacy_variant_requires_opt_in_and_crc():
    assert not C5Decoder().feed(packet(), 0)
    p = C5Decoder(True)
    assert p.feed(packet(), 0)[0].fob_id == 0x87654322
    assert p.counters['observed_len33'] == 1
    assert C5Decoder().feed(packet(declared=38), 0)
    assert not p.feed(packet(declared=34), .1)
    damaged = bytearray(packet()); damaged[20] ^= 1
    assert not p.feed(damaged, .2)
    assert p.counters['crc_error'] == 1


def test_noise_corrupt_length_fragmentation_and_resynchronization():
    p = C5Decoder(True)
    first, second = packet(), packet(identity=0x87654324)
    assert not p.feed(b'noise\x55\xaa\x00\xff\xff' + first[:13], 0)
    rows = p.feed(first[13:] + second, .01)
    assert [r.fob_id for r in rows] == [0x87654322, 0x87654324]
    assert p.counters['bad_outer_length'] > 0
    assert not p.feed(first[:12], .02)
    assert not p.feed(first[12:], .5)
    assert p.counters['partial_timeout'] == 1
    assert p.feed(second, .51)


@pytest.mark.parametrize('value', [-1, 0x100000000, True, 'owner', '0xzz'])
def test_bad_ids(value):
    with pytest.raises(ValueError):canonical_id(value)


def test_canonical_identity_and_bounded_buffer():
    assert canonical_id('2271560482') == canonical_id('0X87654322') == '0x87654322'
    p = C5Decoder(True)
    p.feed(b'!' * 10000, 0)
    assert len(p.buffer) <= 4096
    assert p.feed(packet(), .01)
