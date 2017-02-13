from setuptools import setup, find_packages

exec(open("trio/_version.py", encoding="utf-8").read())

setup(name="trio",
      version=__version__,
      description="An async/await-native I/O library for humans and snake people",
      long_description=open("README.rst", encoding="utf-8").read(),
      author="Nathaniel J. Smith",
      author_email="njs@pobox.com",
      url="https://github.com/njsmith/trio",
      license="MIT -or- Apache License 2.0",
      packages=find_packages(),
      install_requires=[
          "attrs",
          "sortedcontainers",
          "async_generator",
          "cffi; os_name == 'nt'",  # "cffi is required on windows"
      ],
      python_requires=">=3.5",
      classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux"
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: BSD"
        "Operating System :: Microsoft :: Windows"
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Topic :: System :: Networking",
        ],
)
