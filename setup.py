from setuptools import setup, find_packages

exec(open("trio/_version.py").read())

setup(name="trio",
      version=__version__,
      # XX descriptions
      author="Nathaniel J. Smith",
      author_email="njs@pobox.com",
      url="https://github.com/njsmith/trio",
      license="MIT or Apache License, Version 2.0",
      install_requires=[
          "attrs",
          "sortedcontainers",
      ],
      classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: System :: Networking",
        ],
)
