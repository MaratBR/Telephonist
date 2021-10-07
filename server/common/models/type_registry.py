from typing import TypeVar, Generic, Type, Union, Set, List

T = TypeVar('T')


class TypeRegistry(Generic[T]):
    def __init__(self):
        self._types = {}
        self._names = {}

    def expand_names(
            self,
            value: Union[Type[T], str, Set[Union[Type[T], str]], List[Union[Type[T], str]]],
    ) -> List[str]:
        if isinstance(value, set):
            value = list(value)
        elif not isinstance(value, list):
            value = [value]
        for i in range(len(value)):
            if not isinstance(value[i], str):
                try:
                    value[i] = self.get_name(value[i])
                except KeyError:
                    raise ValueError(f'Type {value[i]} has not been registered in the registry "{type(self).__name__}"')
        return value

    def register(self, cls: Type[T], name: str):
        if cls in self._names and name in self._types and self._types[name] == cls and self._names[cls] == name:
            # if we already have this exact pair of the class and the name, we'll just ignore it
            return
        assert name not in self._types and cls not in self._names, (
            f'Type {cls} is already registered in the registry "{type(self).__name__}", '
            f'keep in mind that you can only register a single class with a single name, '
            f'for example you can\'t register the same class with 2 different names or '
            f'2 classes with the same name'
        )
        self._types[name] = cls
        self._names[cls] = name

    def get_type(self, name: str) -> Type[T]:
        return self._types[name]

    def get_name(self, cls: Type[T]):
        return self._names[cls]
