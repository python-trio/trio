from setuptools import find_packages, setup

with open("LONG_DESCRIPTION.rst", encoding="utf8") as f:
    LONG_DESC = f.read()

setup(
    name="trio",
    version="0.0.0",
    description="A friendly Python library for async concurrency and I/O",
    long_description=LONG_DESC,
    long_description_content_type="text/x-rst",
    author="Nathaniel J. Smith",
    author_email="njs@pobox.com",
    url="https://github.com/python-trio/trio",
    license="MIT OR Apache-2.0",
    packages=find_packages(),
    install_requires=[
        # attrs 19.2.0 adds `eq` option to decorators
        # attrs 20.1.0 adds @frozen
        "attrs >= 20.1.0",
        "sortedcontainers",
        "idna",
        "outcome",
        "sniffio >= 1.3.0",
        # cffi 1.12 adds from_buffer(require_writable=True) and ffi.release()
        # cffi 1.14 fixes memory leak inside ffi.getwinerror()
        # cffi is required on Windows, except on PyPy where it is built-in
        "cffi>=1.14; os_name == 'nt' and implementation_name != 'pypy'",
        "exceptiongroup >= 1.0.0rc9; python_version < '3.11'",
    ],
    # This means, just install *everything* you see under trio/, even if it
    # doesn't look like a source file, so long as it appears in MANIFEST.in:
    include_package_data=True,
    python_requires=">=3.8",
    keywords=["async", "io", "networking", "trio"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Framework :: Trio",
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
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Networking",
        "Typing :: Typed",
    ],
    project_urls={
        "Documentation": "https://trio.readthedocs.io/",
        "Changelog": "https://trio.readthedocs.io/en/latest/history.html",
    },
)
