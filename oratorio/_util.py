from functools import wraps

class DispatchTable:
    def __init__(self):
        self._table = {}

    def implements(self, key):
        def wrap(fn):
            self._table[key] = fn
            return fn

    def call(self, key, *args, **kwargs):
        return self._table[key](*args, **kwargs)

    def keys(self):
        return self._table.keys()

