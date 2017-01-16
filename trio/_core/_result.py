import abc
import attr

__all__ = ["Result", "Value", "Error"]

@attr.s(slots=True)
class Result(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def unwrap(self):
        pass

    @abc.abstractmethod
    def send(self, gen):
        pass

    @abc.abstractmethod
    async def asend(self, agen):
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

    @staticmethod
    def combine(old_result, new_result):
        if old_result is None:
            return new_result
        if type(old_result) not in (Value, Error):
            raise TypeError(
                "old_result must be None or Value or Error, not {!r}"
                .format(type(old_result)))
        if type(new_result) not in (Value, Error):
            raise TypeError("new_result must be Value or Error, not {!r}"
                            .format(type(new_result)))
        if type(old_result) is Value:
            if type(new_result) is Value:
                # combine(Value, Value) -> illegal
                raise ValueError("can't combine two Values")
            else:
                # combine(Value, Error) -> Error
                return new_result
        else:
            if type(new_result) is Value:
                # combine(Error, Value) -> Error
                return old_result
            else:
                # combine(Error1, Error2) -> Error2 but with Error1 chained on
                # First, find the end of any existing context chain:
                root = new_result.error
                while True:
                    if root.__cause__ is not None:
                        root = root.__cause__
                    elif root.__suppress_context__:
                        # The user cut off context here (e.g. with "raise from
                        # None"), so we'll discard it and graft our context on
                        # in its place.
                        root.__suppress_context__ = False
                        break
                    elif root.__context__ is not None:
                        root = root.__context__
                    else:
                        break
                root.__context__ = old_result.error
                return new_result

@attr.s(slots=True)
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

@attr.s(slots=True)
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
