from setuptools import setup, find_packages

exec(open("trio/_version.py", encoding="utf-8").read())

LONG_DESC = """\
Trio is an experimental attempt to produce a production-quality,
`permissively licensed
<https://github.com/python-trio/trio/blob/master/LICENSE>`__,
async/await-native I/O library for Python, with an emphasis on
**usability** and **correctness** – we want to make it *easy* to
get things *right*.

Docs: https://trio.readthedocs.io

Issues: https://github.com/python-trio/trio/issues

Repository: https://github.com/python-trio/trio
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
      # Quirky bdist_wheel-specific way:
      # https://wheel.readthedocs.io/en/latest/#defining-conditional-dependencies
      # also supported by pip and setuptools, as long as they're vaguely
      # recent
      extras_require={
          ":os_name == 'nt'": ["cffi"],
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
