from abc import abstractmethod
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

__all__ = ("SessionsBackend", "TSessionData")

TSessionData = TypeVar("TSessionData", bound=BaseModel)


class SessionsBackend:
    @abstractmethod
    async def set(
        self, session_id: str, data: TSessionData, ttl: Optional[float] = None
    ):
        ...

    @abstractmethod
    async def delete(self, session_id: str, session_class: Type[TSessionData]):
        ...

    @abstractmethod
    async def exists(
        self, session_id: str, session_class: Type[TSessionData]
    ) -> bool:
        ...

    @abstractmethod
    async def get(
        self, session_id: str, session_class: Type[TSessionData]
    ) -> Optional[TSessionData]:
        ...
