import pytest

from traceback import extract_tb, print_exception
import sys
import os
import re
from pathlib import Path
import subprocess

from .tutil import slow

from .._multierror import (
    MultiError, format_exception, concat_tb,
)

def raiser1():
    raiser1_2()

def raiser1_2():
    raiser1_3()

def raiser1_3():
    raise ValueError("raiser1_string")

def raiser2():
    raiser2_2()

def raiser2_2():
    raise KeyError("raiser2_string")

def raiser3():
    raise NameError

def get_exc(raiser):
    try:
        raiser()
    except Exception as exc:
        return exc

def get_tb(raiser):
    return get_exc(raiser).__traceback__

def test_concat_tb():

    tb1 = get_tb(raiser1)
    tb2 = get_tb(raiser2)

    # These return a list of (filename, lineno, fn name, text) tuples
    # https://docs.python.org/3/library/traceback.html#traceback.extract_tb
    entries1 = extract_tb(tb1)
    entries2 = extract_tb(tb2)

    tb12 = concat_tb(tb1, tb2)
    assert extract_tb(tb12) == entries1 + entries2

    tb21 = concat_tb(tb2, tb1)
    assert extract_tb(tb21) == entries2 + entries1

    # Check degenerate cases
    assert extract_tb(concat_tb(None, tb1)) == entries1
    assert extract_tb(concat_tb(tb1, None)) == entries1
    assert concat_tb(None, None) is None

    # Make sure the original tracebacks didn't get mutated by mistake
    assert extract_tb(get_tb(raiser1)) == entries1
    assert extract_tb(get_tb(raiser2)) == entries2

def test_MultiError():
    exc1 = get_exc(raiser1)
    exc2 = get_exc(raiser2)

    assert MultiError([exc1]) is exc1
    m = MultiError([exc1, exc2])
    assert m.exceptions == [exc1, exc2]
    assert "ValueError" in str(m)
    assert "ValueError" in repr(m)

    with pytest.raises(TypeError):
        MultiError(object())
    with pytest.raises(TypeError):
        MultiError([KeyError(), ValueError])

def make_tree():
    # Returns an object like:
    #   MultiError([
    #     MultiError([
    #       ValueError,
    #       KeyError,
    #     ]),
    #     NameError,
    #   ])
    # where all exceptions except the root have a non-trivial traceback.
    exc1 = get_exc(raiser1)
    exc2 = get_exc(raiser2)
    exc3 = get_exc(raiser3)

    # Give m12 a non-trivial traceback
    try:
        raise MultiError([exc1, exc2])
    except BaseException as m12:
        return MultiError([m12, exc3])

def assert_tree_eq(m1, m2):
    if m1 is None or m2 is None:
        assert m1 is m2
        return
    assert type(m1) is type(m2)
    assert extract_tb(m1.__traceback__) == extract_tb(m2.__traceback__)
    assert_tree_eq(m1.__cause__, m2.__cause__)
    assert_tree_eq(m1.__context__, m2.__context__)
    if isinstance(m1, MultiError):
        assert len(m1.exceptions) == len(m2.exceptions)
        for e1, e2 in zip(m1.exceptions, m2.exceptions):
            assert_tree_eq(e1, e2)

def test_MultiError_filter():
    def null_handler(exc):
        return exc

    m = make_tree()
    assert_tree_eq(m, m)
    assert MultiError.filter(null_handler, m) is m
    assert_tree_eq(m, make_tree())

    # Make sure we don't pick up any detritus if run in a context where
    # implicit exception chaining would like to kick in
    m = make_tree()
    try:
        raise ValueError
    except ValueError:
        assert MultiError.filter(null_handler, m) is m
    assert_tree_eq(m, make_tree())

    def simple_filter(exc):
        if isinstance(exc, ValueError):
            return None
        if isinstance(exc, KeyError):
            return RuntimeError()
        return exc

    new_m = MultiError.filter(simple_filter, make_tree())
    assert isinstance(new_m, MultiError)
    assert len(new_m.exceptions) == 2
    # was: [[ValueError, KeyError], NameError]
    # ValueError disappeared & KeyError became RuntimeError, so now:
    assert isinstance(new_m.exceptions[0], RuntimeError)
    assert isinstance(new_m.exceptions[1], NameError)

    # implicit chaining:
    assert isinstance(new_m.exceptions[0].__context__, KeyError)

    # also, the traceback on the KeyError incorporates what used to be the
    # traceback on its parent MultiError
    orig = make_tree()
    # make sure we have the right path
    assert isinstance(orig.exceptions[0].exceptions[1], KeyError)
    # get original traceback summary
    orig_extracted = (
        extract_tb(orig.__traceback__)
        + extract_tb(orig.exceptions[0].__traceback__)
        + extract_tb(orig.exceptions[0].exceptions[1].__traceback__)
    )
    def p(exc):
        print_exception(type(exc), exc, exc.__traceback__)
    p(orig)
    p(orig.exceptions[0])
    p(orig.exceptions[0].exceptions[1])
    p(new_m.exceptions[0].__context__)
    # compare to the new path
    assert new_m.__traceback__ is None
    new_extracted = extract_tb(new_m.exceptions[0].__context__.__traceback__)
    assert orig_extracted == new_extracted

    # check preserving partial tree
    def filter_NameError(exc):
        if isinstance(exc, NameError):
            return None
        return exc
    m = make_tree()
    new_m = MultiError.filter(filter_NameError, m)
    # with the NameError gone, the other branch gets promoted
    assert new_m is m.exceptions[0]

    # check fully handling everything
    def filter_all(exc):
        return None
    assert MultiError.filter(filter_all, make_tree()) is None


def test_MultiError_catch():
    # No exception to catch
    noop = lambda _: None  # pragma: no cover
    with MultiError.catch(noop):
        pass

    # Simple pass-through of all exceptions
    m = make_tree()
    with pytest.raises(MultiError) as excinfo:
        with MultiError.catch(lambda exc: exc):
            raise m
    assert excinfo.value is m
    # Should be unchanged, except that we added a traceback frame by raising
    # it here
    assert m.__traceback__ is not None
    assert m.__traceback__.tb_frame.f_code.co_name == "test_MultiError_catch"
    assert m.__traceback__.tb_next is None
    m.__traceback__ = None
    assert_tree_eq(m, make_tree())

    # Swallows everything
    with MultiError.catch(lambda _: None):
        raise make_tree()

    def simple_filter(exc):
        if isinstance(exc, ValueError):
            return None
        if isinstance(exc, KeyError):
            return RuntimeError()
        return exc

    with pytest.raises(MultiError) as excinfo:
        with MultiError.catch(simple_filter):
            raise make_tree()
    new_m = excinfo.value
    assert isinstance(new_m, MultiError)
    assert len(new_m.exceptions) == 2
    # was: [[ValueError, KeyError], NameError]
    # ValueError disappeared & KeyError became RuntimeError, so now:
    assert isinstance(new_m.exceptions[0], RuntimeError)
    assert isinstance(new_m.exceptions[1], NameError)
    # we can't stop Python from attaching the original MultiError to this as a
    # __context__, but we can hide it:
    assert new_m.__suppress_context__

    # check preservation of __cause__ and __context__
    v = ValueError()
    v.__cause__ = KeyError()
    with pytest.raises(ValueError) as excinfo:
        with MultiError.catch(lambda exc: exc):
            raise v
    assert isinstance(excinfo.value.__cause__, KeyError)

    v = ValueError()
    v.__context__ = KeyError()
    with pytest.raises(ValueError) as excinfo:
        with MultiError.catch(lambda exc: exc):
            raise v
    assert isinstance(excinfo.value.__context__, KeyError)
    assert not excinfo.value.__suppress_context__


def assert_match_in_seq(pattern_list, string):
    offset = 0
    print("looking for pattern matches...")
    for pattern in pattern_list:
        print("checking pattern:", pattern)
        reobj = re.compile(pattern)
        match = reobj.search(string, offset)
        assert match is not None
        offset = match.end()

def test_assert_match_in_seq():
    assert_match_in_seq(["a", "b"], "xx a xx b xx")
    assert_match_in_seq(["b", "a"], "xx b xx a xx")
    with pytest.raises(AssertionError):
        assert_match_in_seq(["a", "b"], "xx b xx a xx")

def test_format_exception_multi():
    def einfo(exc):
        return (type(exc), exc, exc.__traceback__)

    exc = get_exc(raiser1)
    formatted = "".join(format_exception(*einfo(exc)))
    assert "raiser1_string" in formatted
    assert "in raiser1_3" in formatted
    assert "raiser2_string" not in formatted
    assert "in raiser2_2" not in formatted
    assert "direct cause" not in formatted
    assert "During handling" not in formatted

    exc = get_exc(raiser1)
    exc.__cause__ = get_exc(raiser2)
    formatted = "".join(format_exception(*einfo(exc)))
    assert "raiser1_string" in formatted
    assert "in raiser1_3" in formatted
    assert "raiser2_string" in formatted
    assert "in raiser2_2" in formatted
    assert "direct cause" in formatted
    assert "During handling" not in formatted

    exc = get_exc(raiser1)
    exc.__context__ = get_exc(raiser2)
    formatted = "".join(format_exception(*einfo(exc)))
    assert "raiser1_string" in formatted
    assert "in raiser1_3" in formatted
    assert "raiser2_string" in formatted
    assert "in raiser2_2" in formatted
    assert "direct cause" not in formatted
    assert "During handling" in formatted

    exc.__suppress_context__ = True
    formatted = "".join(format_exception(*einfo(exc)))
    assert "raiser1_string" in formatted
    assert "in raiser1_3" in formatted
    assert "raiser2_string" not in formatted
    assert "in raiser2_2" not in formatted
    assert "direct cause" not in formatted
    assert "During handling" not in formatted

    # chain=False
    exc = get_exc(raiser1)
    exc.__context__ = get_exc(raiser2)
    formatted = "".join(format_exception(*einfo(exc), chain=False))
    assert "raiser1_string" in formatted
    assert "in raiser1_3" in formatted
    assert "raiser2_string" not in formatted
    assert "in raiser2_2" not in formatted
    assert "direct cause" not in formatted
    assert "During handling" not in formatted

    # limit
    exc = get_exc(raiser1)
    exc.__context__ = get_exc(raiser2)
    # get_exc adds a frame that counts against the limit, so limit=2 means we
    # get 1 deep into the raiser stack
    formatted = "".join(format_exception(*einfo(exc), limit=2))
    print(formatted)
    assert "raiser1_string" in formatted
    assert "in raiser1" in formatted
    assert "in raiser1_2" not in formatted
    assert "raiser2_string" in formatted
    assert "in raiser2" in formatted
    assert "in raiser2_2" not in formatted

    exc = get_exc(raiser1)
    exc.__context__ = get_exc(raiser2)
    formatted = "".join(format_exception(*einfo(exc), limit=1))
    print(formatted)
    assert "raiser1_string" in formatted
    assert "in raiser1" not in formatted
    assert "raiser2_string" in formatted
    assert "in raiser2" not in formatted

    # handles loops
    exc = get_exc(raiser1)
    exc.__cause__ = exc
    formatted = "".join(format_exception(*einfo(exc)))
    assert "raiser1_string" in formatted
    assert "in raiser1_3" in formatted
    assert "raiser2_string" not in formatted
    assert "in raiser2_2" not in formatted
    assert "duplicate exception" in formatted

    # MultiError
    formatted = "".join(format_exception(*einfo(make_tree())))
    print(formatted)

    assert_match_in_seq(
        [
            # Outer exception is MultiError
            r"MultiError:",
            # First embedded exception is the embedded MultiError
            r"\nDetails of embedded exception 1",
            # Which has a single stack frame from make_tree raising it
            r"in make_tree",
            # Then it has two embedded exceptions
            r"  Details of embedded exception 1",
            r"in raiser1_2",
            # for some reason ValueError has no quotes
            r"ValueError: raiser1_string",
            r"  Details of embedded exception 2",
            r"in raiser2_2",
            # But KeyError does have quotes
            r"KeyError: 'raiser2_string'",
            # And finally the NameError, which is a sibling of the embedded
            # MultiError
            r"\nDetails of embedded exception 2:",
            r"in raiser3",
            r"NameError",
        ],
        formatted)

def run_script(name, use_ipython=False):
    import trio
    trio_path = Path(trio.__file__).parent.parent
    script_path = Path(__file__).parent / "test_multierror_scripts" / name

    env = dict(os.environ)
    if "PYTHONPATH" in env:  # pragma: no cover
        pp = env["PYTHONPATH"].split(os.pathsep)
    else:
        pp = []
    pp.insert(0, str(trio_path))
    pp.insert(0, str(script_path.parent))
    env["PYTHONPATH"] = os.pathsep.join(pp)

    if use_ipython:
        lines = [script_path.open().read(), "exit()"]

        cmd = [sys.executable, "-u", "-m", "IPython",
               # no startup files
               "--quick",
               "--TerminalIPythonApp.exec_lines=" + repr(lines),
        ]
    else:
        cmd = [sys.executable, "-u", str(script_path)]
    print("running:", cmd)
    completed = subprocess.run(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    print("process output:")
    print(completed.stdout.decode("utf-8"))
    return completed

def check_simple_excepthook(completed):
    assert_match_in_seq(
        [
            "in <module>",
            "MultiError",
            "Details of embedded exception 1",
            "in exc1_fn",
            "ValueError",
            "Details of embedded exception 2",
            "in exc2_fn",
            "KeyError",
        ],
        completed.stdout.decode("utf-8"))

def test_simple_excepthook():
    completed = run_script("simple_excepthook.py")
    check_simple_excepthook(completed)

def test_custom_excepthook():
    # Check that user-defined excepthooks aren't overridden
    completed = run_script("custom_excepthook.py")
    assert_match_in_seq(
        [
            # The warning
            "RuntimeWarning",
            "already have a custom",
            # The message printed by the custom hook, proving we didn't
            # override it
            "custom running!",
            # The MultiError
            "MultiError:",
        ],
        completed.stdout.decode("utf-8"))

try:
    import IPython
except ImportError:  # pragma: no cover
    have_ipython = False
else:
    have_ipython = True

need_ipython = pytest.mark.skipif(not have_ipython, reason="need IPython")
broken_on_appveyor = pytest.mark.skipif(
    "APPVEYOR" in os.environ,
    reason="For some reason this freezes on appveyor")

@slow
@need_ipython
@broken_on_appveyor
def test_ipython_exc_handler():
    completed = run_script("simple_excepthook.py", use_ipython=True)
    check_simple_excepthook(completed)

@slow
@need_ipython
@broken_on_appveyor
def test_ipython_imported_but_unused():
    completed = run_script("simple_excepthook_IPython.py")
    check_simple_excepthook(completed)

@slow
@need_ipython
@broken_on_appveyor
def test_ipython_custom_exc_handler():
    # Check we get a nice warning (but only one!) if the user is using IPython
    # and already has some other set_custom_exc handler installed.
    completed = run_script("ipython_custom_exc.py", use_ipython=True)
    assert_match_in_seq(
        [
            # The warning
            "RuntimeWarning",
            "IPython detected",
            "skip installing trio",
            # The MultiError
            "MultiError", "ValueError", "KeyError",
        ],
        completed.stdout.decode("utf-8"))
    # Make sure our other warning doesn't show up
    assert "custom sys.excepthook" not in completed.stdout.decode("utf-8")
