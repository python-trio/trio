import pytest
from os import linesep
from .._basic_proto import deframe, FrameError, BufferOverflow, netstring_proto, line_proto


def exact_proto(_, exact):
    while True:
        yield (yield from exact(2))


exact_data = [
    [(b'ab', [b'ab'])],
    [(b'abcdef', [b'ab', b'cd', b'ef'])],
    [(b'abc', [b'ab']), (b'def', [b'cd', b'ef'])],
    [(b'', []), (b'a', []), (b'b', [b'ab'])],
]


@pytest.mark.parametrize(
    "in_out_pairs", exact_data, ids=['one', 'many', 'split', 'by_char']
)
def test_exact(in_out_pairs):
    msgs = deframe(exact_proto)
    for raw, expected in in_out_pairs:
        assert list(msgs(raw)) == expected


def until_proto(until, _):
    while True:
        yield (yield from until(b'!', stop=5))


until_data = [
    [(b'ab!', [b'ab'])],
    [(b'a!bcde!f!', [b'a', b'bcde', b'f'])],
    [(b'ab!c', [b'ab']), (b'd!ef!', [b'cd', b'ef'])],
    [(b'', []), (b'a', []), (b'b', []), (b'!', [b'ab'])],
    [(b'!', [b'']), (b'!!!', [b'', b'', b''])],
]


@pytest.mark.parametrize(
    "in_out_pairs",
    until_data,
    ids=['one', 'many', 'split', 'by_char', 'empty']
)
def test_until(in_out_pairs):
    msgs = deframe(until_proto)
    for raw, expected in in_out_pairs:
        assert list(msgs(raw)) == expected


def test_until_stop():
    msgs = deframe(until_proto)
    assert list(msgs(b'1234!')) == [b'1234']
    with pytest.raises(FrameError):
        list(msgs(b'1234X!'))


def test_until_overflow():
    msgs = deframe(until_proto, maxbuf=10)
    assert list(msgs(b'123!56!89!')) == [b'123', b'56', b'89']
    with pytest.raises(BufferOverflow):
        list(msgs(b'123!56!89!X'))


netstring_data = [
    [(b'2:ab,', ['ab'])],
    [(b'1:a,4:bcde,1:f,!', ['a', 'bcde', 'f'])],
    [(b'2:ab,2:c', ['ab']), (b'd,2', ['cd']), (b':ef,', ['ef'])],
    [(b'1', []), (b':', []), (b'a', []), (b',', ['a'])],
    [(b'0:,', ['']), (b'0:,0:,0:,', ['', '', ''])],
]


@pytest.mark.parametrize(
    "in_out_pairs",
    netstring_data,
    ids=['one', 'many', 'split', 'by_char', 'empty']
)
def test_netstring(in_out_pairs):
    msgs = deframe(netstring_proto)
    for raw, expected in in_out_pairs:
        assert list(msgs(raw)) == expected


def test_netstring_big():
    msgs = deframe(netstring_proto, max_msg=5)
    assert list(msgs(b'5:12345,')) == ['12345']
    with pytest.raises(FrameError):
        list(msgs(b'6:12345X,'))


def test_netstring_bad():
    msgs = deframe(netstring_proto, max_msg=5)
    with pytest.raises(FrameError):
        list(msgs(b'51:2345,'))


def test_line():
    msgs = deframe(line_proto)
    raw = b'Hello World'
    assert list(msgs(raw + linesep.encode())) == [raw]
