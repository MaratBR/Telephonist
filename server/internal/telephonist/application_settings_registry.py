from functools import lru_cache
from typing import *

from pydantic import BaseModel


class SchemaRegistry(dict):
    @lru_cache()
    def schemas(self):
        return dict((k, v.schema()) for k, v in self.items())

    def register(self, name: str):
        def decorator(cls):
            self.add_schema(name, cls)
            return cls

        return decorator

    def add_schema(self, name: str, cls: Type[BaseModel]):
        if name in self:
            raise ValueError(
                f"type {name} is already registered as an application settings type"
            )
        self[name] = cls


builtin_application_settings = SchemaRegistry()
