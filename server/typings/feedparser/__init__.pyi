# Minimal local stub: feedparser ships no type hints and typeshed has no
# types-feedparser package. Only what unspun uses is declared.
import time
from typing import Any, overload

class FeedParserDict(dict[str, Any]):
    entries: list[FeedParserDict]
    bozo: bool | int
    @overload
    def get(self, key: str, /) -> Any | None: ...
    @overload
    def get(self, key: str, default: Any, /) -> Any: ...
    def __getattr__(self, name: str) -> Any: ...

def parse(source: str | bytes, /, **kwargs: Any) -> FeedParserDict: ...

__all__ = ["FeedParserDict", "parse"]
# struct_time is what published_parsed/updated_parsed hold.
_TimeStruct = time.struct_time
