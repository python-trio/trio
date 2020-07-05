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
tag -> `PyPI Search <https://pypi.org/search/?c=Framework+%3A%3A+Trio>`__


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
* `httpx <https://www.python-httpx.org/>`__ - HTTPX is a fully featured HTTP client for Python 3, which provides sync and async APIs, and support for both HTTP/1.1 and HTTP/2.
* `DeFramed <https://github.com/smurfix/deframed>`__ - DeFramed is a Web non-framework that supports a 99%-server-centric approach to Web coding, including support for the `Remi <https://github.com/dddomodossola/remi>`__ GUI library.
* `pura <https://github.com/groove-x/pura>`__ - A simple web framework for embedding realtime graphical visualization into Trio apps, enabling inspection and manipulation of program state during development.


Database
--------

* `triopg <https://github.com/python-trio/triopg>`__ - PostgreSQL client for Trio based on asyncpg.
* `trio-mysql <https://github.com/python-trio/trio-mysql>`__ - Pure Python MySQL Client.
* `sqlalchemy_aio <https://github.com/RazerM/sqlalchemy_aio>`__ - Add asyncio and Trio support to SQLAlchemy core, derived from alchimia.
* `redio <https://github.com/Tronic/redio>`__ - Redis client, pure Python and Trio.
* `trio_redis <https://github.com/omnidots/trio_redis>`__ - A Redis client for Trio. Depends on hiredis-py.


IOT
---
* `DistMQTT <https://github.com/smurfix/distmqtt>`__ - DistMQTT is an open source MQTT client and broker implementation. It is a fork of hbmqtt with support for anyio and DistKV.
* `asyncgpio <https://github.com/python-trio/trio-gpio>`__ - Allows easy access to the GPIO pins on your Raspberry Pi or similar embedded computer.




Building Command Line Apps
--------------------------
* `trio-click <https://github.com/python-trio/trio-click>`__ - Python composable command line utility, trio-compatible version.
* `urwid <https://github.com/urwid/urwid>`__ - Urwid is a console user interface library for Python.


Multi-Core/Multiprocessing
--------------------------
* `tractor <https://github.com/goodboy/tractor>`__ - An experimental, trionic (aka structured concurrent) "actor model" for distributed multi-core Python.
* `Trio run_in_process <https://github.com/ethereum/trio-run-in-process>`__ - Trio based API for running code in a separate process.


RPC
---
* `purepc <https://github.com/standy66/purerpc>`__ - Asynchronous pure Python gRPC client and server implementation using anyio.
* `trio-jsonrpc <https://github.com/HyperionGray/trio-jsonrpc>`__ - JSON-RPC v2.0 for Trio.


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
* `tenacity <https://github.com/jd/tenacity>`__ - Retrying library for Python with async/await support.
* `perf-timer <https://github.com/belm0/perf-timer>`__ - A code timer with Trio async support (see ``TrioPerfTimer``).  Collects execution time of a block of code excluding time when the coroutine isn't scheduled, such as during blocking I/O and sleep.  Also offers ``trio_perf_counter()`` for low-level timing.


Trio/Asyncio Interoperability
-----------------------------
* `anyio <https://github.com/agronholm/anyio>`__ - AnyIO is a asynchronous compatibility API that allows applications and libraries written against it to run unmodified on asyncio, curio and trio.
* `sniffio <https://github.com/python-trio/sniffio>`__ - This is a tiny package whose only purpose is to let you detect which async library your code is running under.
* `trio-asyncio <https://github.com/python-trio/trio-asyncio>`__ - Trio-Asyncio lets you use many asyncio libraries from your Trio app.
