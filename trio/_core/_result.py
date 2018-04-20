import outcome

from .. import _deprecate

__all__ = ["Result", "Value", "Error"]

_deprecate.enable_attribute_deprecations(__name__)


class Result(outcome.Outcome):
    @classmethod
    @_deprecate.deprecated(
        version="0.5.0", issue=494, instead="outcome.capture"
    )
    def capture(cls, sync_fn, *args):
        return outcome.capture(sync_fn, *args)

    @classmethod
    @_deprecate.deprecated(
        version="0.5.0", issue=494, instead="outcome.acapture"
    )
    async def acapture(cls, async_fn, *args):
        return await outcome.acapture(async_fn, *args)


# alias these types so they don't mysteriously disappear
Value = outcome.Value
Error = outcome.Error

# ensure that isinstance(Value(), Result)/issubclass(Value, Result) and etc
# don't break
Result.register(Value)
Result.register(Error)