from typing import Union

from typing_extensions import Protocol

from ._core._run import _TaskStatus, _TaskStatusIgnored


class _HasFileno(Protocol):
    def fileno(self) -> int:
        ...


TaskStatus = Union[_TaskStatus, _TaskStatusIgnored]
