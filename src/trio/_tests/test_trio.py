from __future__ import annotations

import subprocess
import sys


def test_trio_import() -> None:
    for module in list(sys.modules.keys()):
        if module.startswith("trio"):
            del sys.modules[module]

    import trio  # noqa: F401


def test_trio_import_does_not_import_asyncio() -> None:
    res = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, trio; assert 'asyncio' not in sys.modules, f'unexpected asyncio modules: {[m for m in sys.modules if \"asyncio\" in m]}'",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"import trio loaded asyncio:\n{res.stderr}"
