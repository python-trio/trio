from setuptools import setup, find_packages

exec(open("trio/_version.py", encoding="utf-8").read())

LONG_DESC = """\
.. image:: https://cdn.rawgit.com/python-trio/trio/9b0bec646a31e0d0f67b8b6ecc6939726faf3e17/logo/logo-with-background.svg
   :width: 200px
   :align: right

The Trio project's goal is to produce a production-quality, `permissively
licensed <https://github.com/python-trio/trio/blob/master/LICENSE>`__,
async/await-native I/O library for Python. Like all async libraries,
its main purpose is to help you write programs that do **multiple
things at the same time** with **parallelized I/O**. A web spider that
wants to fetch lots of pages in parallel, a web server that needs to
juggle lots of downloads and websocket connections at the same time, a
process supervisor monitoring multiple subprocesses... that sort of
thing. Compared to other libraries, Trio attempts to distinguish
itself with an obsessive focus on **usability** and
**correctness**. Concurrency is complicated; we try to make it *easy*
to get things *right*.

Trio was built from the ground up to take advantage of the `latest
Python features <https://www.python.org/dev/peps/pep-0492/>`__, and
draws inspiration from `many sources
<https://github.com/python-trio/trio/wiki/Reading-list>`__, in
particular Dave Beazley's `Curio <https://curio.readthedocs.io/>`__.
The resulting design is radically simpler than older competitors like
`asyncio <https://docs.python.org/3/library/asyncio.html>`__ and
`Twisted <https://twistedmatrix.com/>`__, yet just as capable. Trio is
the Python I/O library I always wanted; I find it makes building
I/O-oriented programs easier, less error-prone, and just plain more
fun. `Perhaps you'll find the same
<https://github.com/python-trio/trio/wiki/Testimonials>`__.

This project is young and still somewhat experimental: the overall
design is solid and the existing features are fully tested and
documented, but you may encounter missing functionality or rough
edges. We *do* encourage you do use it, but you should `read and
subscribe to issue #1
<https://github.com/python-trio/trio/issues/1>`__ to get warning and a
chance to give feedback about any compatibility-breaking changes.

Vital statistics:

* Supported environments: Linux, macOS, or Windows running some kind of Python
  3.6-or-better (either CPython or PyPy3 is fine). \\*BSD and illumos likely
  work too, but are not tested.

* Install: ``python3 -m pip install -U trio`` (or on Windows, maybe
  ``py -3 -m pip install -U trio``). No compiler needed.

* Tutorial and reference manual: https://trio.readthedocs.io

* Bug tracker and source code: https://github.com/python-trio/trio

* Real-time chat: https://gitter.im/python-trio/general

* Discussion forum: https://trio.discourse.group

* License: MIT or Apache 2, your choice

* Contributor guide: https://trio.readthedocs.io/en/latest/contributing.html

* Code of conduct: Contributors are requested to follow our `code of
  conduct
  <https://trio.readthedocs.io/en/latest/code-of-conduct.html>`_
  in all project spaces.
"""

setup(
    name="trio",
    version=__version__,
    description="A friendly Python library for async concurrency and I/O",
    long_description=LONG_DESC,
    author="Nathaniel J. Smith",
    author_email="njs@pobox.com",
    url="https://github.com/python-trio/trio",
    license="MIT -or- Apache License 2.0",
    packages=find_packages(),
    install_requires=[
        "attrs >= 19.2.0",  # for eq
        "sortedcontainers",
        "async_generator >= 1.9",
        "idna",
        "outcome",
        "sniffio",
        # cffi 1.12 adds from_buffer(require_writable=True) and ffi.release()
        # cffi 1.14 fixes memory leak inside ffi.getwinerror()
        # cffi is required on Windows, except on PyPy where it is built-in
        "cffi>=1.14; os_name == 'nt' and implementation_name != 'pypy'",
        "contextvars>=2.1; python_version < '3.7'",
    ],
    # This means, just install *everything* you see under trio/, even if it
    # doesn't look like a source file, so long as it appears in MANIFEST.in:
    include_package_data=True,
    python_requires=">=3.6",
    keywords=["async", "io", "networking", "trio"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: BSD",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Topic :: System :: Networking",
        "Framework :: Trio",
    ],
)
