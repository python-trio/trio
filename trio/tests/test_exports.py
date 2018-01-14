import trio
import trio.testing

from .. import _core


def test_core_is_properly_reexported():
    # Each export from _core should be re-exported by exactly one of these
    # three modules:
    sources = [trio, trio.hazmat, trio.testing]
    for symbol in _core.__all__:
        found = 0
        for source in sources:
            if (
                symbol in source.__all__
                and getattr(source, symbol) is getattr(_core, symbol)
            ):
                found += 1
        print(symbol, found)
        assert found == 1
