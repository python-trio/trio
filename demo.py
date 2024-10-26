import trio


async def main():
    err = None
    with trio.CancelScope() as scope:
        scope.cancel()
        try:
            await trio.sleep_forever()
        except BaseException as e:
            err = e
            raise
    breakpoint()


# trio.run(main)

import gc

import objgraph
from anyio import CancelScope, get_cancelled_exc_class


async def test_exception_refcycles_propagate_cancellation_error() -> None:
    """Test that TaskGroup deletes cancelled_exc"""
    exc = None

    with CancelScope() as cs:
        cs.cancel()
        try:
            await trio.sleep_forever()
        except get_cancelled_exc_class() as e:
            exc = e
            raise

    assert isinstance(exc, get_cancelled_exc_class())
    gc.collect()
    objgraph.show_chain(
        objgraph.find_backref_chain(
            gc.get_referrers(exc)[0],
            objgraph.is_proper_module,
        ),
    )


# trio.run(test_exception_refcycles_propagate_cancellation_error)


class MyException(Exception):
    pass


async def main():
    raise MyException


def inner():
    try:
        trio.run(main)
    except MyException:
        pass


import refcycle

gc.disable()
gc.collect()
inner()
garbage = refcycle.garbage()
for i, component in enumerate(garbage.source_components()):
    component.export_image(f"{i}_example.svg")
garbage.export_image("example.svg")
