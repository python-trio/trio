def test_trio_import() -> None:
    import sys

    for module in list(sys.modules.keys()):
        if module.startswith("trio"):
            del sys.modules[module]

    import trio  # ruff:ignore[unused-import]
