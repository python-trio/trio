import outcome

from .._deprecate import deprecated

__all__ = ["Result", "Value", "Error"]


class Result(outcome.Outcome):
    @deprecated(version="0.5.0", issue=494, instead="outcome.Outcome")
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def capture(cls, sync_fn, *args):
        return outcome.capture(sync_fn, *args)

    @classmethod
    async def acapture(cls, async_fn, *args):
        return await outcome.acapture(async_fn, *args)


# alias these types so they don't mysteriously disappear
Value = outcome.Value
Error = outcome.Error

# ensure that isinstance(Value(), Result)/issubclass(Value, Result) and etc
# don't break
Result.register(Value)
Result.register(Error)
