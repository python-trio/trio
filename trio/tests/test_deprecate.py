import pytest

import inspect
import warnings

from .._deprecate import TrioDeprecationWarning, warn_deprecated, deprecated, deprecated_alias


@pytest.fixture
def recwarn_always(recwarn):
    warnings.simplefilter("always")
    return recwarn


def _here():
    info = inspect.getframeinfo(inspect.currentframe().f_back)
    return (info.filename, info.lineno)


def test_warn_deprecated(recwarn_always):
    def deprecated_thing():
        warn_deprecated("ice", version="1.2", alternative="water")

    filename, lineno = _here()  # https://github.com/google/yapf/issues/447
    deprecated_thing()
    assert len(recwarn_always) == 1
    got = recwarn_always.pop(TrioDeprecationWarning)
    assert "ice is deprecated" in got.message.args[0]
    assert "Trio 1.2" in got.message.args[0]
    assert "water instead" in got.message.args[0]
    assert got.filename == filename
    assert got.lineno == lineno + 1


def test_warn_deprecated_no_alternative(recwarn_always):
    # Explicitly no alternative
    warn_deprecated("water", version="1.3", alternative=None)
    assert len(recwarn_always) == 1
    got = recwarn_always.pop(TrioDeprecationWarning)
    assert "water is deprecated" in got.message.args[0]
    assert "Trio 1.3" in got.message.args[0]


def test_warn_deprecated_stacklevel(recwarn_always):
    def nested1():
        nested2()

    def nested2():
        warn_deprecated("x", version="1.3", alternative="y", stacklevel=3)

    filename, lineno = _here()  # https://github.com/google/yapf/issues/447
    nested1()
    got = recwarn_always.pop(TrioDeprecationWarning)
    assert got.filename == filename
    assert got.lineno == lineno + 1


def old():  # pragma: no cover
    pass


def new():  # pragma: no cover
    pass


def test_warn_deprecated_formatting(recwarn_always):
    warn_deprecated(old, version="1.0", alternative=new)
    got = recwarn_always.pop(TrioDeprecationWarning)
    assert "test_deprecate.old is deprecated" in got.message.args[0]
    assert "test_deprecate.new instead" in got.message.args[0]


@deprecated(version="1.5", alternative=new)
def deprecated_old():
    return 3


def test_deprecated_decorator(recwarn_always):
    assert deprecated_old() == 3
    got = recwarn_always.pop(TrioDeprecationWarning)
    assert "test_deprecate.deprecated_old is deprecated" in got.message.args[0]
    assert "1.5" in got.message.args[0]
    assert "test_deprecate.new" in got.message.args[0]


class Foo:
    @deprecated(version="1.0", alternative="crying")
    def method(self):
        return 7


def test_deprecated_decorator_method(recwarn_always):
    f = Foo()
    assert f.method() == 7
    got = recwarn_always.pop(TrioDeprecationWarning)
    assert "test_deprecate.Foo.method is deprecated" in got.message.args[0]


@deprecated(thing="you know, the thing", version=1.2, alternative=None)
def deprecated_with_thing():
    return 72


def test_deprecated_decorator_with_explicit_thing(recwarn_always):
    assert deprecated_with_thing() == 72
    got = recwarn_always.pop(TrioDeprecationWarning)
    assert "you know, the thing is deprecated" in got.message.args[0]


def new_hotness():
    return "new hotness"


old_hotness = deprecated_alias("old_hotness", new_hotness, version="1.23")


def test_deprecated_alias(recwarn_always):
    assert old_hotness() == "new hotness"
    got = recwarn_always.pop(TrioDeprecationWarning)
    assert "test_deprecate.old_hotness is deprecated" in got.message.args[0]
    assert "1.23" in got.message.args[0]
    assert "test_deprecate.new_hotness instead" in got.message.args[0]


class Alias:
    def new_hotness_method(self):
        return "new hotness method"

    old_hotness_method = deprecated_alias(
        "Alias.old_hotness_method", new_hotness_method, version="3.21"
    )


def test_deprecated_alias_method(recwarn_always):
    obj = Alias()
    assert obj.old_hotness_method() == "new hotness method"
    got = recwarn_always.pop(TrioDeprecationWarning)
    msg = got.message.args[0]
    assert "test_deprecate.Alias.old_hotness_method is deprecated" in msg
    assert "test_deprecate.Alias.new_hotness_method instead" in msg
