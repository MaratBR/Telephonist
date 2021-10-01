import math
from enum import Enum
from typing import Optional, List, Type, Generic, TypeVar, Union, Set

from beanie import Document
from beanie.odm.enums import SortDirection
from fastapi import Query, Depends
from pydantic.generics import GenericModel

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


class Pagination:
    def __init__(self,
                 page: int = Query(1, gt=0),
                 page_size: int = Query(20, gt=4)):
        self.page = page
        self.page_size = page_size


class OrderingDirection(str, Enum):
    ASC = 'asc'
    DESC = 'desc'


TPaginationItem = TypeVar('TPaginationItem')


class PaginationResult(GenericModel, Generic[TPaginationItem]):
    result: List[TPaginationItem]
    page: int
    page_size: int
    total: int
    pages_total: int
    ordered_by: str
    order: OrderingDirection


class PaginationWithOrdering(Pagination):
    def __init__(self,
                 page: int = Query(1, gt=0),
                 page_size: int = Query(20, gt=4),
                 field: Optional[str] = Query(None),
                 order: Optional[OrderingDirection] = Query(OrderingDirection.DESC)):
        super(PaginationWithOrdering, self).__init__(page, page_size)
        self.field = field
        self.order = order

    @classmethod
    def from_choices(cls, choices: List[str]):
        FieldEnum = Enum('FieldEnum', {k: k for k in choices})

        class NewType(cls):
            def __init__(self,
                         page: int = Query(1, gt=0),
                         page_size: int = Query(20, gt=4),
                         field: Optional[FieldEnum] = Query(None),
                         order: Optional[OrderingDirection] = Query(OrderingDirection.DESC)):
                if isinstance(field, Enum):
                    field = str(field)[len(type(field).__name__) + 1:]
                super(NewType, self).__init__(page, page_size, field, order)

        return Depends(NewType)

    async def paginate(self, cls: Type[Document]):
        q = cls.find()
        order = self.order or OrderingDirection.ASC
        ordered_by = self.field or '_id'
        print(ordered_by)
        q = q.sort((ordered_by, SortDirection.DESCENDING if order == OrderingDirection.DESC else SortDirection.ASCENDING))
        total = await q.count()
        q = q.skip((self.page - 1) * self.page_size).limit(self.page_size)
        items = await q.to_list()

        return PaginationResult(
            result=items,
            page=self.page,
            page_size=self.page_size,
            total=total,
            pages_total=math.ceil(total / self.page_size),
            ordered_by=ordered_by,
            order=order
        )
