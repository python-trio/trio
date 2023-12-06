from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

import pytest

from trio.testing import Matcher, RaisesGroup

# TODO: make a public export

if TYPE_CHECKING:
    from typing_extensions import assert_type

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup, ExceptionGroup


class TestRaisesGroup:
    def test_raises_group(self) -> None:
        with pytest.raises(
            ValueError,
            match="^Invalid argument {exc} must be exception type, Matcher, or RaisesGroup.$",
        ):
            RaisesGroup(ValueError())

        with RaisesGroup(ValueError):
            raise ExceptionGroup("foo", (ValueError(),))

        with RaisesGroup(SyntaxError):
            with RaisesGroup(ValueError):
                raise ExceptionGroup("foo", (SyntaxError(),))

        # multiple exceptions
        with RaisesGroup(ValueError, SyntaxError):
            raise ExceptionGroup("foo", (ValueError(), SyntaxError()))

        # order doesn't matter
        with RaisesGroup(SyntaxError, ValueError):
            raise ExceptionGroup("foo", (ValueError(), SyntaxError()))

        # nested exceptions
        with RaisesGroup(RaisesGroup(ValueError)):
            raise ExceptionGroup("foo", (ExceptionGroup("bar", (ValueError(),)),))

        with RaisesGroup(
            SyntaxError,
            RaisesGroup(ValueError),
            RaisesGroup(RuntimeError),
        ):
            raise ExceptionGroup(
                "foo",
                (
                    SyntaxError(),
                    ExceptionGroup("bar", (ValueError(),)),
                    ExceptionGroup("", (RuntimeError(),)),
                ),
            )

        # will error if there's excess exceptions
        with pytest.raises(ExceptionGroup):
            with RaisesGroup(ValueError):
                raise ExceptionGroup("", (ValueError(), ValueError()))

        with pytest.raises(ExceptionGroup):
            with RaisesGroup(ValueError):
                raise ExceptionGroup("", (RuntimeError(), ValueError()))

        # will error if there's missing exceptions
        with pytest.raises(ExceptionGroup):
            with RaisesGroup(ValueError, ValueError):
                raise ExceptionGroup("", (ValueError(),))

        with pytest.raises(ExceptionGroup):
            with RaisesGroup(ValueError, SyntaxError):
                raise ExceptionGroup("", (ValueError(),))

        # loose semantics, as with expect*
        with RaisesGroup(ValueError, strict=False):
            raise ExceptionGroup("", (ExceptionGroup("", (ValueError(),)),))

        # mixed loose is possible if you want it to be at least N deep
        with RaisesGroup(RaisesGroup(ValueError, strict=False)):
            raise ExceptionGroup("", (ExceptionGroup("", (ValueError(),)),))
        with RaisesGroup(RaisesGroup(ValueError, strict=False)):
            raise ExceptionGroup(
                "", (ExceptionGroup("", (ExceptionGroup("", (ValueError(),)),)),)
            )
        with pytest.raises(ExceptionGroup):
            with RaisesGroup(RaisesGroup(ValueError, strict=False)):
                raise ExceptionGroup("", (ValueError(),))

        # but not the other way around
        with pytest.raises(
            ValueError,
            match="^You cannot specify a nested structure inside a RaisesGroup with strict=False$",
        ):
            RaisesGroup(RaisesGroup(ValueError), strict=False)

        # currently not fully identical in behaviour to expect*, which would also catch an unwrapped exception
        with pytest.raises(ValueError):
            with RaisesGroup(ValueError, strict=False):
                raise ValueError

    def test_match(self) -> None:
        # supports match string
        with RaisesGroup(ValueError, match="bar"):
            raise ExceptionGroup("bar", (ValueError(),))

        with pytest.raises(ExceptionGroup):
            with RaisesGroup(ValueError, match="foo"):
                raise ExceptionGroup("bar", (ValueError(),))

    def test_check(self) -> None:
        exc = ExceptionGroup("", (ValueError(),))
        with RaisesGroup(ValueError, check=lambda x: x is exc):
            raise exc
        with pytest.raises(ExceptionGroup):
            with RaisesGroup(ValueError, check=lambda x: x is exc):
                raise ExceptionGroup("", (ValueError(),))

    def test_RaisesGroup_matches(self) -> None:
        eeg = RaisesGroup(ValueError)
        assert not eeg.matches(None)
        assert not eeg.matches(ValueError())
        assert eeg.matches(ExceptionGroup("", (ValueError(),)))

    def test_message(self) -> None:
        with pytest.raises(
            AssertionError,
            match=re.escape(
                f"DID NOT RAISE any exception, expected ExceptionGroup({ValueError!r},)"
            ),
        ):
            with RaisesGroup(ValueError):
                ...
        with pytest.raises(
            AssertionError,
            match=re.escape(
                f"DID NOT RAISE any exception, expected ExceptionGroup(ExceptionGroup({ValueError!r},),)"
            ),
        ):
            with RaisesGroup(RaisesGroup(ValueError)):
                ...

    def test_matcher(self) -> None:
        with pytest.raises(
            ValueError, match="^You must specify at least one parameter to match on.$"
        ):
            Matcher()

        with RaisesGroup(Matcher(ValueError)):
            raise ExceptionGroup("", (ValueError(),))
        with pytest.raises(ExceptionGroup):
            with RaisesGroup(Matcher(TypeError)):
                raise ExceptionGroup("", (ValueError(),))

    def test_matcher_match(self) -> None:
        with RaisesGroup(Matcher(ValueError, "foo")):
            raise ExceptionGroup("", (ValueError("foo"),))
        with pytest.raises(ExceptionGroup):
            with RaisesGroup(Matcher(ValueError, "foo")):
                raise ExceptionGroup("", (ValueError("bar"),))

        # Can be used without specifying the type
        with RaisesGroup(Matcher(match="foo")):
            raise ExceptionGroup("", (ValueError("foo"),))
        with pytest.raises(ExceptionGroup):
            with RaisesGroup(Matcher(match="foo")):
                raise ExceptionGroup("", (ValueError("bar"),))

    def test_Matcher_check(self) -> None:
        def check_oserror_and_errno_is_5(e: BaseException) -> bool:
            return isinstance(e, OSError) and e.errno == 5

        with RaisesGroup(Matcher(check=check_oserror_and_errno_is_5)):
            raise ExceptionGroup("", (OSError(5, ""),))

        # specifying exception_type narrows the parameter type to the callable
        def check_errno_is_5(e: OSError) -> bool:
            return e.errno == 5

        with RaisesGroup(Matcher(OSError, check=check_errno_is_5)):
            raise ExceptionGroup("", (OSError(5, ""),))

        with pytest.raises(ExceptionGroup):
            with RaisesGroup(Matcher(OSError, check=check_errno_is_5)):
                raise ExceptionGroup("", (OSError(6, ""),))

    if TYPE_CHECKING:
        # getting the typing working satisfactory is very tricky
        # but with RaisesGroup being seen as a subclass of BaseExceptionGroup
        # most end-user cases of checking excinfo.value.foobar should work fine now.
        def test_types_0(self) -> None:
            _: BaseExceptionGroup[ValueError] = RaisesGroup(ValueError)
            _ = RaisesGroup(RaisesGroup(ValueError))  # type: ignore[arg-type]
            a: BaseExceptionGroup[BaseExceptionGroup[ValueError]]
            a = RaisesGroup(RaisesGroup(ValueError))
            a = BaseExceptionGroup("", (BaseExceptionGroup("", (ValueError(),)),))
            assert a

        def test_types_1(self) -> None:
            with RaisesGroup(ValueError) as e:
                raise ExceptionGroup("foo", (ValueError(),))
            assert_type(e.value, BaseExceptionGroup[ValueError])
            # assert_type(e.value, RaisesGroup[ValueError])

        def test_types_2(self) -> None:
            exc: ExceptionGroup[ValueError] | ValueError = ExceptionGroup(
                "", (ValueError(),)
            )
            if RaisesGroup(ValueError).matches(exc):
                assert_type(exc, BaseExceptionGroup[ValueError])

        def test_types_3(self) -> None:
            e: BaseExceptionGroup[KeyboardInterrupt] = BaseExceptionGroup(
                "", (KeyboardInterrupt(),)
            )
            if RaisesGroup(ValueError).matches(e):
                assert_type(e, BaseExceptionGroup[ValueError])

        def test_types_4(self) -> None:
            with RaisesGroup(Matcher(ValueError)) as e:
                ...
            _: BaseExceptionGroup[ValueError] = e.value
            assert_type(e.value, BaseExceptionGroup[ValueError])

        def test_types_5(self) -> None:
            with RaisesGroup(RaisesGroup(ValueError)) as excinfo:
                raise ExceptionGroup("foo", (ValueError(),))
            _: BaseExceptionGroup[BaseExceptionGroup[ValueError]] = excinfo.value
            assert_type(
                excinfo.value,
                BaseExceptionGroup[RaisesGroup[ValueError]],
            )
            print(excinfo.value.exceptions[0].exceptions[0])

        def test_types_6(self) -> None:
            exc: ExceptionGroup[ExceptionGroup[ValueError]] = ExceptionGroup(
                "", (ExceptionGroup("", (ValueError(),)),)
            )
            if RaisesGroup(RaisesGroup(ValueError)).matches(exc):
                # ugly
                assert_type(exc, BaseExceptionGroup[RaisesGroup[ValueError]])
