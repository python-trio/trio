from typing_extensions import Protocol


class _HasFileno(Protocol):
    def fileno(self) -> int:
        ...
