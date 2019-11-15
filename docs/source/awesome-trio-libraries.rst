Awesome Trio Libraries
======================

.. List of Trio Libraries

   A list of libraries that support Trio, similar to the awesome-python
   list here: https://github.com/vinta/awesome-python/


.. currentmodule:: trio

You have completed the tutorial, and are enthusiastic about building
great new applications and libraries with async functionality.
However, to get much useful work done you will want to use some of
the great libraries that support Trio-flavoured concurrency. This list
is not complete, but gives a starting point. Another great way to find
Trio-compatible libraries is to search on PyPI for the ``Framework :: Trio``
tag -> `PyPI Search <https://pypi.org/search/?q=Framework+%3A%3A+Trio>`__


Getting Started
---------------
* `cookiecutter-trio <https://github.com/python-trio/cookiecutter-trio>`__ - This is a cookiecutter template for Python projects that use Trio. It makes it easy to start a new project, by providing a bunch of preconfigured boilerplate. 
* `pytest-trio <https://github.com/python-trio/pytest-trio>`__ - Pytest plugin to test async-enabled Trio functions.
* `sphinxcontrib-trio <https://github.com/python-trio/sphinxcontrib-trio>`__ - Make Sphinx better at documenting Python functions and methods. In particular, it makes it easy to document async functions.


Web and HTML
------------
* `asks <https://github.com/theelous3/asks>`__ - asks is an async requests-like http library.
* `trio-websocket <https://github.com/HyperionGray/trio-websocket>`__ - This library implements the WebSocket protocol, striving for safety, correctness, and ergonomics.
* `quart-trio <https://gitlab.com/pgjones/quart-trio/>`__ - Like Flask, but for Trio. A simple and powerful framework for building async web applications and REST APIs. Tip: this is an ASGI-based framework, so you'll also need an HTTP server with ASGI support.
* `hypercorn <https://gitlab.com/pgjones/hypercorn>`__ - An HTTP server for hosting your ASGI apps. Supports HTTP/1.1, HTTP/2, HTTP/3, and Websockets. Can be run as a standalone server, or embedded in a larger Trio app. Use it with ``quart-trio``, or any other Trio-compatible ASGI framework.


Database
--------

* `triopg <https://github.com/python-trio/triopg>`__ - PostgreSQL client for Trio based on asyncpg.
* `trio-mysql <https://github.com/python-trio/trio-mysql>`__ - Pure Python MySQL Client.
* `sqlalchemy_aio <https://github.com/RazerM/sqlalchemy_aio>`__ - Add asyncio and Trio support to SQLAlchemy core, derived from alchimia.


Building Command Line Apps
--------------------------
* `trio-click <https://github.com/python-trio/trio-click>`__ - Python composable command line utility, trio-compatible version.


Multi-Core/Multiprocessing
--------------------------
* `tractor <https://github.com/goodboy/tractor>`__ - tractor is an attempt to bring trionic structured concurrency to distributed multi-core Python.


Testing
-------
* `pytest-trio <https://github.com/python-trio/pytest-trio>`__ - Pytest plugin for trio.
* `hypothesis-trio <https://github.com/python-trio/hypothesis-trio>`__ - Hypothesis plugin for trio.
* `trustme <https://github.com/python-trio/trustme>`__ - #1 quality TLS certs while you wait, for the discerning tester.


Tools and Utilities
-------------------
* `trio-typing <https://github.com/python-trio/trio-typing>`__ - Type hints for Trio and related projects.
* `trio-util <https://github.com/groove-x/trio-util>`__ - An assortment of utilities for the Trio async/await framework.
* `tricycle <https://github.com/oremanj/tricycle>`__ - This is a library of interesting-but-maybe-not-yet-fully-proven extensions to Trio.


Trio/Asyncio Interoperability
-----------------------------
* `anyio <https://github.com/agronholm/anyio>`__ - AnyIO is a asynchronous compatibility API that allows applications and libraries written against it to run unmodified on asyncio, curio and trio.
* `sniffio <https://github.com/python-trio/sniffio>`__ - This is a tiny package whose only purpose is to let you detect which async library your code is running under.
* `trio-asyncio <https://github.com/python-trio/trio-asyncio>`__ - Trio-Asyncio lets you use many asyncio libraries from your Trio app.

