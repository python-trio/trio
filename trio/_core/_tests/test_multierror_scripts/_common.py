# https://coverage.readthedocs.io/en/latest/subprocess.html
try:
    import coverage
except ImportError:  # pragma: no cover
    pass
else:
    import os
    print(os.environ["COVERAGE_PROCESS_START"])
    # raise Exception("this *is* executing, right?")
    coverage.process_startup()
