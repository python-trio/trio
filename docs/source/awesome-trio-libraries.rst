Awesome Trio Libraries
======================

.. List of Trio Libraries

   A list of libraries that support Trio, similar to the awesome-python
   list here: https://github.com/vinta/awesome-python/


.. currentmodule:: trio

You have completed the turorial, and are enthusiastic about building
great new applications and libraries with async functionality.
However, to get much useful work done you will want to use some of
the great libraries that support trio-flavoured concurrency. This list
is not complete, but gives a starting point. Another great way to find
trio-compatible libraries is to search on PyPI for the `Framework :: trio`
tag -> `PyPI Search <https://pypi.org/search/?q=Framework+%3A%3A+trio>`__


Core Trio Libraries
-------------------

These libraries are part of the `python-trio Github team <https://github.com/python-trio>`__ and will be used in
many trio projects:

* `cookiecutter-trio <https://github.com/python-trio/cookiecutter-trio>`__ - Quickstart template for Trio projects
* `pytest-trio <https://github.com/python-trio/pytest-trio>`__ - Pytest plugin for trio
* `trio-typing <https://github.com/python-trio/trio-typing>`__ - Type hints for Trio and related projects
* `sphinxcontrib-trio <https://github.com/python-trio/sphinxcontrib-trio>`__ - Make Sphinx better at documenting Python functions and methods
* `trio-click <https://github.com/python-trio/trio-click>`__ - Python composable command line utility, trio-compatible version
* `triopg <https://github.com/python-trio/triopg>`__ - PostgreSQL client for Trio based on asyncpg
* `trio-mysql <https://github.com/python-trio/trio-mysql>`__ - Pure Python MySQL Client
* `hypothesis-trio <https://github.com/python-trio/hypothesis-trio>`__ - Hypothesis plugin for trio


Web and HTML Libraries
----------------------

* `asks <https://github.com/theelous3/asks>`__ - asks is an async requests-like http library
* `trustme <https://github.com/python-trio/trustme>`__ - #1 quality TLS certs while you wait, for the discerning tester
* `trio-websocket <https://github.com/HyperionGray/trio-websocket>`__ - This library implements the WebSocket protocol, striving for safety, correctness, and ergonomics.
* `quart-trio <https://gitlab.com/pgjones/quart-trio/>`__ - `Quart <https://gitlab.com/pgjones/quart>`__ is a Python ASGI web microframework with the same API as Flask and Quart-Trio is an extension for Quart to support the Trio event loop.


Database Libraries
------------------

* `triopg <https://github.com/python-trio/triopg>`__ - PostgreSQL client for Trio based on asyncpg
* `trio-mysql <https://github.com/python-trio/trio-mysql>`__ - Pure Python MySQL Client
* `sqlalchemy_aio <https://github.com/RazerM/sqlalchemy_aio>`__ - Add asyncio and Trio support to SQLAlchemy core, derived from alchimia.

Tools and Utility Libraries
---------------------------
* `anyio <https://github.com/agronholm/anyio>`__ - AnyIO is a asynchronous compatibility API that allows applications and libraries written against it to run unmodified on asyncio, curio and trio.
* `tractor <https://github.com/goodboy/tractor>`__ - tractor is an attempt to bring trionic structured concurrency to distributed multi-core Python.
* `sniffio <https://github.com/python-trio/sniffio>`__ - This is a tiny package whose only purpose is to let you detect which async library your code is running under.
