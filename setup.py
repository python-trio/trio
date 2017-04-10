from setuptools import setup, find_packages

exec(open("trio/_version.py", encoding="utf-8").read())

LONG_DESC = """\
Trio is an experimental attempt to produce a production-quality,
`permissively licensed
<https://github.com/python-trio/trio/blob/master/LICENSE>`__,
async/await-native I/O library for Python, with an emphasis on
**usability** and **correctness** – we want to make it *easy* to
get things *right*. Our ultimate goal is to become Python's de facto
standard async I/O library.

This is project is young and still somewhat experimental: the overall
design is solid and the existing features are fully tested and
documented, but you may encounter missing functionality or rough
edges. We *do* encourage you do use it, but you should `read and
subscribe to this issue
<https://github.com/python-trio/trio/issues/1>`__ to get warning and a
chance to give feedback about any compatibility-breaking changes.

Vital statistics:

* Supported environments: Linux, MacOS, or Windows running some kind of Python
  3.5-or-better (either CPython or PyPy3 is fine). *BSD and illumus likely
  work too, but are not tested.

* Install: ``python3 -m pip install -U trio`` (or on Windows, maybe
  ``py -3 -m pip install -U trio``). No compiler needed.

* Tutorial and reference manual: https://trio.readthedocs.io

* Bug tracker and source code: https://github.com/python-trio/trio

* License: MIT or Apache 2, your choice

* Code of conduct: Contributors are requested to follow our `code of
  conduct
  <https://github.com/python-trio/trio/blob/master/CODE_OF_CONDUCT.md>`_
  in all project spaces.
"""

setup(name="trio",
      version=__version__,
      description="An async/await-native I/O library for humans and snake people",
      long_description=LONG_DESC,
      author="Nathaniel J. Smith",
      author_email="njs@pobox.com",
      url="https://github.com/python-trio/trio",
      license="MIT -or- Apache License 2.0",
      packages=find_packages(),
      install_requires=[
          "attrs",
          "sortedcontainers",
          "async_generator >= 1.6",
          # PEP 508 style, but:
          # https://bitbucket.org/pypa/wheel/issues/181/bdist_wheel-silently-discards-pep-508
          #"cffi; os_name == 'nt'",  # "cffi is required on windows"
      ],
      # This means, just install *everything* you see under trio/, even if it
      # doesn't look like a source file, so long as it appears in MANIFEST.in:
      include_package_data=True,
      # Quirky bdist_wheel-specific way:
      # https://wheel.readthedocs.io/en/latest/#defining-conditional-dependencies
      # also supported by pip and setuptools, as long as they're vaguely
      # recent
      extras_require={
          ":os_name == 'nt'": ["cffi"],  # "cffi is required on windows"
      },
      python_requires=">=3.5",
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
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Topic :: System :: Networking",
      ],
)
