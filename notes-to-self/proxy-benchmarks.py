import textwrap
import io
import time

methods = {"fileno"}

class Proxy1:
    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __getattr__(self, name):
        if name in methods:
            return getattr(self._wrapped, name)
        raise AttributeError(name)

################################################################

class Proxy2:
    def __init__(self, wrapped):
        self._wrapped = wrapped

def add_wrapper(cls, method):
    def wrapper(self, *args, **kwargs):
        return getattr(self._wrapped, method)(*args, **kwargs)
    setattr(cls, method, wrapper)

for method in methods:
    add_wrapper(Proxy2, method)

################################################################

class Proxy3:
    def __init__(self, wrapped):
        self._wrapped = wrapped

def add_wrapper(cls, method):
    code = textwrap.dedent("""
        def wrapper(self, *args, **kwargs):
            return self._wrapped.{}(*args, **kwargs)
    """.format(method))
    ns = {}
    exec(code, ns)
    setattr(cls, method, ns["wrapper"])

for method in methods:
    add_wrapper(Proxy3, method)

################################################################

class Proxy4:
    def __init__(self, wrapped):
        self._wrapped = wrapped

def add_wrapper(cls, attr):
    def getter(self):
        return getattr(self._wrapped, attr)

    def setter(self, newval):
        setattr(self._wrapped, attr, newval)

    def deleter(self):
        delattr(self._wrapped, attr)

    setattr(cls, attr, property(getter, setter, deleter))

for method in methods:
    add_wrapper(Proxy4, method)

################################################################

class Proxy5:
    def __init__(self, wrapped):
        self._wrapped = wrapped

def add_wrapper(cls, attr):
    code = textwrap.dedent("""
        def getter(self):
            return self._wrapped.{attr}

        def setter(self, newval):
            self._wrapped.{attr} = newval

        def deleter(self):
            del self._wrapped.{attr}
    """.format(attr=attr))
    ns = {}
    exec(code, ns)
    setattr(cls, attr, property(ns["getter"], ns["setter"], ns["deleter"]))

for method in methods:
    add_wrapper(Proxy5, method)

################################################################

# methods only
class Proxy6:
    def __init__(self, wrapper):
        self._wrapper = wrapper

        for method in methods:
            setattr(self, method, getattr(self._wrapper, method))
    

################################################################

classes = [Proxy1, Proxy2, Proxy3, Proxy4, Proxy5, Proxy6]

def check(cls):
    with open("/etc/passwd") as f:
        p = cls(f)
        assert p.fileno() == f.fileno()

for cls in classes:
    check(cls)

f = open("/etc/passwd")
objs = [c(f) for c in classes]

COUNT = 1000000
try:
    import __pypy__
except ImportError:
    pass
else:
    COUNT *= 10

while True:
    print("-------")
    for obj in objs:
        start = time.time()
        for _ in range(COUNT):
            obj.fileno()
        end = time.time()
        print("{!r}: {:.2f}".format(obj, end - start))
