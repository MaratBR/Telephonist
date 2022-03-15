import inspect
from typing import Any, ClassVar, Generic, Optional, Type, TypeVar

__ANNOTATIONS__ = "__o_annotations__"


def _get_or_set_annotations(o) -> dict:
    if not hasattr(o, __ANNOTATIONS__):
        setattr(o, __ANNOTATIONS__, {})
    return getattr(o, __ANNOTATIONS__)


def _annotate(f, annotation_type, metadata: Optional[Any]):
    annotations = _get_or_set_annotations(f)
    annotations[annotation_type] = metadata
    return f


T = TypeVar("T")


class AnnotatedMember(Generic[T]):
    __slots__ = ("member", "name", "metadata")

    member: Any
    name: str
    metadata: T

    def __init__(self, member: Any, name: str, metadata: T):
        self.member = member
        self.name = name
        self.metadata = metadata

    def __repr__(self):
        return (
            f"AnnotatedMember(name={self.name}, metadata={self.metadata},"
            f" member={self.member})"
        )


class Annotation(Generic[T]):
    __cache: ClassVar[dict] = {}

    def __init__(
        self,
        name: Optional[str] = None,
        __type_argument__: Optional[Any] = None,
    ):
        self.name = name
        self.__type_argument__ = __type_argument__

    def __call__(self, metadata: T):
        def decorator(o):
            _annotate(o, self.name, metadata)
            return o

        return decorator

    def __repr__(self):
        if self.__type_argument__:
            return (
                f"{self.__class__.__name__}({self.name},"
                f" {self.__type_argument__})"
            )
        return f"{self.__class__.__name__}({self.name})"

    def members(self, o) -> list[AnnotatedMember[T]]:
        members = inspect.getmembers(o, lambda m: has_annotation(m, self.name))
        return [
            AnnotatedMember(
                name=name,
                member=m,
                metadata=getattr(m, __ANNOTATIONS__)[self.name],
            )
            for (name, m) in members
        ]

    def methods(self, o):
        return list(
            filter(lambda m: inspect.isfunction(m.member), self.members(o))
        )


def create_annotation(
    metadata_type: Type[T],
    name: str,
) -> Annotation[T]:
    return Annotation(name, __type_argument__=metadata_type)


def has_annotation(o, annotation):
    return hasattr(o, __ANNOTATIONS__) and annotation in getattr(
        o, __ANNOTATIONS__
    )


def main():
    annotation: Annotation[str] = Annotation()

    class A:
        @annotation(12)
        def a(self):
            pass

    print(annotation.members(A()))


if __name__ == "__main__":
    main()
