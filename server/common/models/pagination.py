import inspect
import math
import time
import warnings
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    List,
    Mapping,
    Optional,
    Set,
    Type,
    TypeVar,
    Union,
)

from beanie import Document
from beanie.odm.enums import SortDirection
from fastapi.params import Depends
from pydantic import Field
from pydantic.generics import GenericModel

__all__ = (
    "OrderingDirection",
    "PaginationParameters",
    "Pagination",
    "PaginationResult",
)

from server.common.models import AppBaseModel


class OrderingDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


TPaginationItem = TypeVar("TPaginationItem")


class PaginationParameters(AppBaseModel):
    page: int = Field(1, gt=1)
    page_size: int = Field(20, gt=0, lt=100)
    pages_returned: int = Field(1, gt=0, lt=10)
    order: OrderingDirection = OrderingDirection.DESC
    order_by: Optional[str]


class PaginationResult(GenericModel, Generic[TPaginationItem]):
    meta: Optional[Any]
    page: int
    page_size: int
    total: int
    pages_total: int
    order_by: str
    order: OrderingDirection
    pages_returned: int
    result: List[TPaginationItem]


_order_by_types_cache = {}


def _create_order_by_enum(default_option: str, options: Set[str]):
    options = sorted({default_option, *options})
    typename = "OrderBy_" + "_".join(options)
    if typename in _order_by_types_cache:
        return _order_by_types_cache[typename], getattr(
            _order_by_types_cache[typename], default_option
        )
    enum_class = Enum(typename, {v: v for v in options})  # type: ignore
    _order_by_types_cache[typename] = enum_class
    return enum_class, getattr(enum_class, default_option)


class Pagination:
    max_pages_per_request: int = 10
    max_page_size: int = 1000
    min_page_size: int = 10
    default_page_size: int = 50
    ordered_by_options: Set[str] = {"_id"}
    default_order_by: str = "_id"
    descending_by_default: bool = False
    use_order_by: bool = True
    allow_page_size: bool = True
    allow_pages_batch: bool = True
    enforce_page_lower_bound: bool = False
    fields_mapping: Mapping[str, str] = {}

    if TYPE_CHECKING:
        # minimal version of parameters
        class Parameters(AppBaseModel):
            page: int

    def __init_subclass__(cls, **kwargs):
        if cls.max_pages_per_request < 1:
            warnings.warn(
                f"{cls.__name__}.max_pages_per_request is less than 1, value"
                " will be ignored"
            )
        if cls.max_page_size < 1:
            warnings.warn(
                f"{cls.__name__}.max_page_size is less than 1, value will be"
                " ignored"
            )
        if not hasattr(cls, "Parameters"):

            class Parameters(AppBaseModel):
                if cls.enforce_page_lower_bound:
                    page: int = Field(1, gt=1)
                else:
                    page: int = 1
                if cls.allow_pages_batch:
                    pages_returned: int = Field(
                        1, gt=0, lt=cls.max_pages_per_request
                    )
                if cls.allow_page_size:
                    page_size: int = Field(
                        cls.default_page_size,
                        ge=cls.min_page_size,
                        le=cls.max_page_size,
                    )
                if cls.use_order_by:
                    (
                        __order_by_enum__,
                        __order_by_enum_default__,
                    ) = _create_order_by_enum(
                        cls.default_order_by, cls.ordered_by_options
                    )
                    order: OrderingDirection = (
                        OrderingDirection.DESC
                        if cls.descending_by_default
                        else OrderingDirection.ASC
                    )
                    order_by: __order_by_enum__ = __order_by_enum_default__

            cls.Parameters = Parameters
        else:
            assert inspect.isclass(cls.Parameters)

        if cls.__init__ is Pagination.__init__:

            def __init__(self, params: cls.Parameters = Depends()):
                Pagination.__init__(self, params)

            cls.__init__ = __init__

    def __init__(self, params):
        self.params = params
        if not self.enforce_page_lower_bound and params.page < 1:
            params.page = 1

    async def paginate(
        self,
        cls: Type[Document],
        project: Optional[Type[AppBaseModel]] = None,
        filter_condition: Optional[
            Union[dict[str, Any], List[dict[str, Any]], List[bool]]
        ] = None,
    ):
        if filter_condition:
            q = (
                cls.find(*filter_condition)
                if isinstance(filter_condition, list)
                else cls.find(filter_condition)
            )
        else:
            q = cls.find()
        total = await q.count()

        if self.use_order_by:
            q = q.sort(
                (
                    self.fields_mapping.get(
                        self.params.order_by.value, self.params.order_by.value
                    ),
                    SortDirection.DESCENDING
                    if self.params.order == OrderingDirection.DESC
                    else SortDirection.ASCENDING,
                )
            )
        if self.params.page > 1:
            q = q.skip((self.params.page - 1) * self.params.page_size)
        q = q.limit(
            self.params.page_size * self.params.pages_returned
            if self.allow_pages_batch
            else self.params.page_size
        )
        if project:
            q = q.project(project)

        now = time.time_ns()
        items = await q.to_list()
        elapsed = time.time_ns() - now

        # NOTE we know it's valid
        return PaginationResult.construct(
            meta={"db:took": elapsed / 1000000},
            result=items,
            page=self.params.page,
            page_size=self.params.page_size,
            total=total,
            pages_total=math.ceil(total / self.params.page_size),
            order_by=self.params.order_by.value,
            order=self.params.order,
            pages_returned=math.ceil(len(items) / self.params.page_size),
        )
