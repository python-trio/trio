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
* `httpx <https://www.python-httpx.org/>`__ - HTTPX is a fully featured HTTP client for Python 3, which provides sync and async APIs, and support for both HTTP/1.1 and HTTP/2.
* `trio-websocket <https://github.com/HyperionGray/trio-websocket>`__ - A WebSocket client and server implementation striving for safety, correctness, and ergonomics.
* `quart-trio <https://gitlab.com/pgjones/quart-trio/>`__ - Like Flask, but for Trio. A simple and powerful framework for building async web applications and REST APIs. Tip: this is an ASGI-based framework, so you'll also need an HTTP server with ASGI support.
* `hypercorn <https://gitlab.com/pgjones/hypercorn>`__ - An HTTP server for hosting your ASGI apps. Supports HTTP/1.1, HTTP/2, HTTP/3, and Websockets. Can be run as a standalone server, or embedded in a larger Trio app. Use it with ``quart-trio``, or any other Trio-compatible ASGI framework.
* `DeFramed <https://github.com/smurfix/deframed>`__ - DeFramed is a Web non-framework that supports a 99%-server-centric approach to Web coding, including support for the `Remi <https://github.com/dddomodossola/remi>`__ GUI library.
* `pura <https://github.com/groove-x/pura>`__ - A simple web framework for embedding realtime graphical visualization into Trio apps, enabling inspection and manipulation of program state during development.
* `pyscalpel <https://scalpel.readthedocs.io/en/latest/>`__ - A fast and powerful webscraping library.
* `muffin <https://github.com/klen/muffin>`_ - Muffin is a fast, simple ASGI web-framework
* `asgi-tools <https://github.com/klen/asgi-tools>`_ - Tools to quickly build lightest ASGI apps (also contains a test client with lifespan, websocket support)
* `starlette <https://github.com/encode/starlette>`_ - The little ASGI framework that shines.


Database
--------

* `triopg <https://github.com/python-trio/triopg>`__ - PostgreSQL client for Trio based on asyncpg.
* `trio-mysql <https://github.com/python-trio/trio-mysql>`__ - Pure Python MySQL Client.
* `sqlalchemy_aio <https://github.com/RazerM/sqlalchemy_aio>`__ - Add asyncio and Trio support to SQLAlchemy core, derived from alchimia.
* `redio <https://github.com/Tronic/redio>`__ - Redis client, pure Python and Trio.
* `trio_redis <https://github.com/omnidots/trio_redis>`__ - A Redis client for Trio. Depends on hiredis-py.
* `asyncakumuli <https://github.com/M-o-a-T/asyncakumuli>`__ - Client for the `Akumuli <https://akumuli.org/>`__ time series database.
* `aio-databases <https://github.com/klen/aio-databases>`_ - Async Support for various databases (triopg, trio-mysql)
* `peewee-aio <https://github.com/klen/peewee-aio>`_ - Peewee Async ORM with trio support (triopg, trio-mysql).


IOT
---
* `DistMQTT <https://github.com/M-o-a-T/distmqtt>`__ - DistMQTT is an open source MQTT client and broker implementation. It is a fork of hbmqtt with support for anyio and DistKV.
* `asyncgpio <https://github.com/python-trio/trio-gpio>`__ - Allows easy access to the GPIO pins on your Raspberry Pi or similar embedded computer.
* `asyncowfs <https://github.com/M-o-a-T/asyncowfs>`__ - High-level, object-oriented access to 1wire sensors and actors.
* `DistKV <https://github.com/M-o-a-T/distkv>`__ - a persistent, distributed, master-less key/value storage with async notification and some IoT-related plug-ins.


Building Command Line Apps
--------------------------
* `trio-click <https://github.com/python-trio/trio-click>`__ - Python composable command line utility, trio-compatible version.
* `urwid <https://github.com/urwid/urwid>`__ - Urwid is a console user interface library for Python.


Building GUI Apps
-----------------
* `QTrio <https://qtrio.readthedocs.io/en/stable/>`__ - Integration between Trio and either the PyQt or PySide Qt wrapper libraries.  Uses Trio's :ref:`guest mode <guest-mode>`.


Multi-Core/Multiprocessing
--------------------------
* `tractor <https://github.com/goodboy/tractor>`__ - An experimental, trionic (aka structured concurrent) "actor model" for distributed multi-core Python.
* `Trio run_in_process <https://github.com/ethereum/trio-run-in-process>`__ - Trio based API for running code in a separate process.
* `trio-parallel <https://trio-parallel.readthedocs.io/>`__ - CPU parallelism for Trio


Stream Processing
-----------------
* `Slurry <https://github.com/andersea/slurry>`__ - Slurry is a microframework for building reactive, data processing applications with Trio.


RPC
---
* `purepc <https://github.com/python-trio/purerpc>`__ - Native, async Python gRPC client and server implementation using anyio.


Testing
-------
* `pytest-trio <https://github.com/python-trio/pytest-trio>`__ - Pytest plugin for trio.
* `hypothesis-trio <https://github.com/python-trio/hypothesis-trio>`__ - Hypothesis plugin for trio.
* `trustme <https://github.com/python-trio/trustme>`__ - #1 quality TLS certs while you wait, for the discerning tester.
* `pytest-aio <https://github.com/klen/pytest-aio>`_ - Pytest plugin with support for trio, curio, asyncio


Tools and Utilities
-------------------
* `trio-typing <https://github.com/python-trio/trio-typing>`__ - Type hints for Trio and related projects.
* `trio-util <https://github.com/groove-x/trio-util>`__ - An assortment of utilities for the Trio async/await framework.
* `flake8-trio <https://github.com/Zac-HD/flake8-trio>`__ - Highly opinionated linter for various sorts of problems in Trio and/or AnyIO. Can run as a flake8 plugin, or standalone with support for autofixing some errors.
* `tricycle <https://github.com/oremanj/tricycle>`__ - This is a library of interesting-but-maybe-not-yet-fully-proven extensions to Trio.
* `tenacity <https://github.com/jd/tenacity>`__ - Retrying library for Python with async/await support.
* `perf-timer <https://github.com/belm0/perf-timer>`__ - A code timer with Trio async support (see ``TrioPerfTimer``).  Collects execution time of a block of code excluding time when the coroutine isn't scheduled, such as during blocking I/O and sleep.  Also offers ``trio_perf_counter()`` for low-level timing.
* `aiometer <https://github.com/florimondmanca/aiometer>`__ - Execute lots of tasks concurrently while controlling concurrency limits
* `triotp <https://linkdd.github.io/triotp>`__ - OTP framework for Python Trio

Trio/Asyncio Interoperability
-----------------------------
* `anyio <https://github.com/agronholm/anyio>`__ - AnyIO is a asynchronous compatibility API that allows applications and libraries written against it to run unmodified on asyncio, curio and trio.
* `sniffio <https://github.com/python-trio/sniffio>`__ - This is a tiny package whose only purpose is to let you detect which async library your code is running under.
* `trio-asyncio <https://github.com/python-trio/trio-asyncio>`__ - Trio-Asyncio lets you use many asyncio libraries from your Trio app.
