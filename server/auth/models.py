import base64
import hashlib
import re
from datetime import timedelta, datetime
from typing import Optional, Tuple, Type, Union

import nanoid
from beanie import Document, Indexed, PydanticObjectId
from beanie.operators import Eq
from pydantic import BaseModel, Field, EmailStr
from pymongo.errors import DuplicateKeyError

from server.auth.hash import hash_password
from server.auth.tokens import create_static_token, encode_token, decode_token
from server.common.models import TypeRegistry
from server.database import register_model


class TokenSubjectError(Exception):
    pass


class UnknownTokenSubject(TokenSubjectError):
    def __init__(self, subject: Union[str, Type[Document]]):
        super(UnknownTokenSubject, self).__init__(f'unknown token subject: {subject}')


class TokenSubjectID(str):
    regex = re.compile(r'^(\w+)/([0-9a-f]{24})$', re.IGNORECASE)

    @property
    def oid(self):
        return PydanticObjectId(self.split('/')[1])

    @property
    def type(self):
        return token_subjects_registry.get_type(self.type_name)

    @property
    def type_name(self):
        return self.split('/')[0]

    @classmethod
    def from_document(cls, doc: Document):
        str_repr = f'{token_subjects_registry.get_name(type(doc))}/{doc.id}'
        return TokenSubjectID(str_repr)

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(
            pattern=r'^\w+/[0-9a-f]{24}$',
            examples=['user/45cbc4a0e4123f6920000002', 'application/45cbc4a0e4123f6920000002'],
        )

    @classmethod
    def validate(cls, v):
        if not isinstance(v, str):
            raise TypeError('string required')
        m = cls.regex.fullmatch(v.lower())
        if not m:
            raise ValueError('invalid subject id format: ' + v)

        return cls(v)


class TokenModel(BaseModel):
    sub: TokenSubjectID
    exp: Optional[int]
    jti: str = Field(default_factory=nanoid.generate)
    token_type: str

    def encode(self) -> str:
        return encode_token(self.token_dict())

    @classmethod
    def decode(cls, token: str):
        return cls(**decode_token(token))

    def token_dict(self):
        d: dict = self.dict()
        d = dict(filter(lambda item: item[1] is not None, d.items()))
        if len(d['scope']) > 0:
            d['scope'] = list(d['scope'])
        else:
            del d['scope']
        return d


class TokenSubjectMixin(BaseModel):
    __subject_name__: Optional[str]

    def __init_subclass__(cls, **kwargs):
        super(TokenSubjectMixin, cls).__init_subclass__(**kwargs)
        assert issubclass(cls, Document), 'Only Document classes can be used as a subject for token'
        if cls.__module__ == 'pydantic.main':
            return
        token_subjects_registry.register(cls, getattr(cls, '__subject_name__', cls.__name__.lower()))

    def create_token(
            self: Document,
            token_type: Optional[str] = 'access',
            jti: Optional[str] = None,
            lifetime: Optional[timedelta] = None
    ):
        return TokenModel(
            token_type=token_type,
            sub=TokenSubjectID.from_document(self),
            jti=jti,
            exp=None if lifetime is None else (datetime.utcnow() + lifetime).timestamp()
        )


class _TokenSubjectsRegistry(TypeRegistry[TokenSubjectMixin]):
    pass


token_subjects_registry: TypeRegistry[TokenSubjectMixin] = _TokenSubjectsRegistry()


@register_model
class User(Document, TokenSubjectMixin):
    username: Indexed(str, unique=True)
    email: Optional[EmailStr] = None
    password_hash: str
    disabled: bool = False

    class Collection:
        name = 'users'
        indexes = ['email', 'disabled']

    class View(BaseModel):
        username: str
        disabled: bool
        id: PydanticObjectId

        @property
        def created_at(self) -> datetime:
            return self.id.generation_time

    def __str__(self):
        return self.username

    @classmethod
    async def by_username(
            cls,
            username: str,
            include_disabled: bool = False
    ) -> Optional['User']:
        q = cls if include_disabled else cls.find(cls.disabled == False)
        q = cls.find(cls.username == username)
        q = q.limit(1)
        results = await q.to_list()
        if len(results) == 0:
            return None
        return results[0]

    @classmethod
    async def create_user(
            cls,
            username: str,
            password: str,
            email: Optional[EmailStr] = None
    ):
        user = cls(username=username, password_hash=hash_password(password), email=email)
        await user.save()
        return user

    @classmethod
    async def populate(cls):
        try:
            await cls.create_user('admin', 'admin')
            await cls.create_user('1', '1')
        except DuplicateKeyError:
            pass


@register_model
class BlockedAccessToken(Document):
    id: str
    blocked_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    async def block(cls, token_id: str):
        if await cls.is_blocked(token_id):
            return
        blocked_token = cls(id=token_id)
        await blocked_token.save()

    @classmethod
    async def is_blocked(cls, token_id: str) -> bool:
        return await cls.find(cls.id == token_id).count() > 0


@register_model
class RefreshToken(Document):
    id: str
    expiration_date: datetime
    blocked: bool = False
    last_used: Optional[datetime] = None
    user_id: PydanticObjectId

    @classmethod
    async def is_blocked(cls, token: str) -> bool:
        return await cls.find(cls.id == cls._make_token_id(token)).count() > 0

    @classmethod
    async def find_valid(cls, token: str) -> Optional['RefreshToken']:
        return await cls.find_one(
            cls.id == cls._make_token_id(token),
            Eq(cls.blocked, False),
            cls.expiration_date > datetime.utcnow()
        )

    @classmethod
    async def create_token(cls, user: User, lifetime: timedelta) -> Tuple['RefreshToken', str]:
        token = create_static_token(10)
        refresh_token = cls(
            user_id=user.id,
            expiration_date=datetime.utcnow() + lifetime,
            id=cls._make_token_id(token))
        await refresh_token.save()
        return refresh_token, token

    def matches(self, token: str):
        return self.id == base64.urlsafe_b64encode(hashlib.sha256(token).digest())[:43].decode('ascii')

    @staticmethod
    def _make_token_id(token: str):
        return base64.urlsafe_b64encode(hashlib.sha256(token).digest())[:43].decode('ascii')
