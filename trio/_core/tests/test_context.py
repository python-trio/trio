from contextvars import ContextVar, copy_context

from .._run import CancelScope
from .._context import set_current_context

var = ContextVar("var")


async def test_context_change():
    var.set("abc")

    new_context = copy_context()
    async with set_current_context(new_context):
        assert var.get() == "abc"
        var.set("def")
        assert var.get() == "def"

    assert var.get() == "abc"


async def test_context_change_with_cancellation():
    var.set("qqq")

    new_context = copy_context()
    with CancelScope() as scope:
        async with set_current_context(new_context):
            var.set("ghj")
            assert var.get() == "ghj"
            scope.cancel()

    assert var.get() == "qqq"
