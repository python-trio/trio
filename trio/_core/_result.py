import abc
import attr

__all__ = ["Result", "Value", "Error"]

@attr.s(slots=True, frozen=True)
class Result(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def unwrap(self):  # pragma: no cover
        pass

    @abc.abstractmethod
    def send(self, gen):  # pragma: no cover
        pass

    @abc.abstractmethod
    async def asend(self, agen):  # pragma: no cover
        pass

    @staticmethod
    def capture(fn, *args):
        try:
            return Value(fn(*args))
        except BaseException as exc:
            return Error(exc)

    @staticmethod
    async def acapture(fn, *args):
        try:
            return Value(await fn(*args))
        except BaseException as exc:
            return Error(exc)


@attr.s(slots=True, frozen=True, repr=False)
class Value(Result):
    value = attr.ib()

    def __repr__(self):
        return "Value({!r})".format(self.value)

    def unwrap(self):
        return self.value

    def send(self, gen):
        return gen.send(self.value)

    async def asend(self, agen):
        return await agen.asend(self.value)


@attr.s(slots=True, frozen=True, repr=False)
class Error(Result):
    error = attr.ib(validator=attr.validators.instance_of(BaseException))

    def __repr__(self):
        return "Error({!r})".format(self.error)

    def unwrap(self):
        raise self.error

    def send(self, it):
        return it.throw(self.error)

    async def asend(self, agen):
        return await agen.athrow(self.error)
