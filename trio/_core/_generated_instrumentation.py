# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
from __future__ import annotations

from typing import TYPE_CHECKING

from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._run import GLOBAL_RUN_CONTEXT

if TYPE_CHECKING:
    from ._instrumentation import Instrument


def add_instrument(instrument: Instrument) -> None:
    """Start instrumenting the current run loop with the given instrument.

    Args:
      instrument (trio.abc.Instrument): The instrument to activate.

    If ``instrument`` is already active, does nothing.

    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.instruments.add_instrument(instrument)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None


def remove_instrument(instrument: Instrument) -> None:
    """Stop instrumenting the current run loop with the given instrument.

    Args:
      instrument (trio.abc.Instrument): The instrument to de-activate.

    Raises:
      KeyError: if the instrument is not currently active. This could
          occur either because you never added it, or because you added it
          and then it raised an unhandled exception and was automatically
          deactivated.

    """
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.instruments.remove_instrument(instrument)
    except AttributeError:
        raise RuntimeError("must be called from async context") from None
