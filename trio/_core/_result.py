import abc
import attr

__all__ = ["Result", "Value", "Error"]

@attr.s(slots=True, frozen=True)
class Result(metaclass=abc.ABCMeta):
    """An abstract class representing the result of a Python computation.

    This class has two concrete subclasses: :class:`Value` representing a
    value, and :class:`Error` representing an exception.

    In addition to the methods described below, comparison operators on
    :class:`Value` and :class:`Error` objects (``==``, ``<``, etc.) check that
    the other object is also a :class:`Value` or :class:`Error` object
    respectively, and then compare the contained objects.

    :class:`Result` objects are hashable if the contained objects are
    hashable.

    """

    @staticmethod
    def capture(sync_fn, *args):
        """Run ``sync_fn(*args)`` and capture the result.

        Returns:
          Either a :class:`Value` or :class:`Error` as appropriate.

        """
        try:
            return Value(sync_fn(*args))
        except BaseException as exc:
            return Error(exc)

    @staticmethod
    async def acapture(async_fn, *args):
        """Run ``await async_fn(*args)`` and capture the result.

        Returns:
          Either a :class:`Value` or :class:`Error` as appropriate.

        """
        try:
            return Value(await async_fn(*args))
        except BaseException as exc:
            return Error(exc)

    @abc.abstractmethod
    def unwrap(self):
        """Return or raise the contained value or exception.

        These two lines of code are equivalent::

           x = fn(*args)
           x = Result.capture(fn, *args).unwrap()

        """

    @abc.abstractmethod
    def send(self, gen):
        """Send or throw the contained value or exception into the given
        generator object.

        Args:
          gen: A generator object supporting ``.send()`` and ``.throw()``
              methods.

        """

    @abc.abstractmethod
    async def asend(self, agen):
        """Send or throw the contained value or exception into the given async
        generator object.

        Args:
          agen: An async generator object supporting ``.asend()`` and
              ``.athrow()`` methods.

        """


@attr.s(slots=True, frozen=True, repr=False)
class Value(Result):
    """Concrete :class:`Result` subclass representing a regular value.

    """

    value = attr.ib()
    """The contained value."""

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
    """Concrete :class:`Result` subclass representing a raised exception.

    """

    error = attr.ib(validator=attr.validators.instance_of(BaseException))
    """The contained exception object."""

    def __repr__(self):
        return "Error({!r})".format(self.error)

    def unwrap(self):
        raise self.error

    def send(self, it):
        return it.throw(self.error)

    async def asend(self, agen):
        return await agen.athrow(self.error)
