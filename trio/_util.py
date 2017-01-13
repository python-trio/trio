class DispatchTable:
    def __init__(self):
        self._table = {}

    def implements(self, key):
        def capture(fn):
            self._table[key] = fn
            return fn
        return capture

    def call(self, key, *args, **kwargs):
        return self._table[key](*args, **kwargs)

    def keys(self):
        return self._table.keys()

