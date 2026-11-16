from __future__ import annotations

import inspect
from typing import NoReturn

import pytest

from ..testing import MockClock, trio_test

RUN_SLOW = True
SKIP_OPTIONAL_IMPORTS = False
SKIP_SSL_IMPORTS = False


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-slow", action="store_true", help="run slow tests")
    parser.addoption(
        "--skip-optional-imports",
        action="store_true",
        help="skip tests that rely on libraries not required by trio itself",
    )
    parser.addoption(
        "--skip-ssl-imports",
        action="store_true",
        help="skip tests that rely on cryptography",
    )


def pytest_configure(config: pytest.Config) -> None:
    global RUN_SLOW, SKIP_OPTIONAL_IMPORTS, SKIP_SSL_IMPORTS
    RUN_SLOW = config.getoption("--run-slow", default=True)
    SKIP_OPTIONAL_IMPORTS = config.getoption("--skip-optional-imports", default=False)
    SKIP_SSL_IMPORTS = config.getoption("--skip-ssl-imports", default=False)


@pytest.fixture
def mock_clock() -> MockClock:
    return MockClock()


@pytest.fixture
def autojump_clock() -> MockClock:
    return MockClock(autojump_threshold=0)


# FIXME: split off into a package (or just make part of Trio's public
# interface?), with config file to enable? and I guess a mark option too; I
# guess it's useful with the class- and file-level marking machinery (where
# the raw @trio_test decorator isn't enough).
@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> None:
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        pyfuncitem.obj = trio_test(pyfuncitem.obj)


def maybe_ignore_import_error(error: ImportError) -> NoReturn:
    if SKIP_OPTIONAL_IMPORTS or (SKIP_SSL_IMPORTS and error.name == "cryptography"):
        pytest.skip(error.msg, allow_module_level=True)
    else:  # pragma: no cover
        raise error
