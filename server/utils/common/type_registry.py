from typing import Dict, Generic, Type, TypeVar

TBound = TypeVar("TBound")


class TypeRegistry(Generic[TBound], Dict[str, Type[TBound]]):
    def register(self, key: str):
        def decorator(type_: Type[TBound]):
            self.set_or_raise(key, type_)
            return type_

        return decorator

    def set_or_raise(self, key: str, type_: Type[TBound]):
        assert (
            key not in self
        ), f"{key} is already registered in a {type(self).__name__}"
        self[key] = type_

    def require(self, key: str):
        assert key in self, f"{key} is missing in {type(self).__name__}"
        return key

    KeyType: Type[str] = str
