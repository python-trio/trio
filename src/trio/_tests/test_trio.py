def test_trio_import() -> None:
    import sys

    for module in list(sys.modules.keys()):
        if module.startswith("trio"):
            del sys.modules[module]

    import trio  # noqa: F401


def test_we_have_peek() -> None:
    """
    temporary test to see if we are running on outcome v2
    """
    import outcome

    def fn() -> int:
        return 1

    assert outcome.capture(fn).peek() == 1
