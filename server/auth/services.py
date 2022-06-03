import secrets
from datetime import datetime, timedelta
from typing import Optional, Type, TypeVar, Union

from beanie import PydanticObjectId
from beanie.operators import Eq
from fastapi import Depends
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from server.common.channels.layer import ChannelLayer, get_channel_layer
from server.settings import Settings, get_settings

from .dependencies import session_cookie
from .exceptions import InvalidToken
from .models import User, UserSession
from .token import TokenModel

TokenType = TypeVar("TokenType", bound=TokenModel)


class PasswordHashingService:
    def __init__(self):
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash_password(self, password: str) -> str:
        return self.pwd_context.hash(password)

    def verify_password(
        self, plain_password: str, hashed_password: str
    ) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)


class TokenService:
    def __init__(self, settings: Settings = Depends(get_settings)):
        self._settings = settings

    def decode_raw(self, token: str) -> dict:
        try:
            return jwt.decode(
                token,
                self._settings.secret.get_secret_value(),
                issuer=self._settings.jwt_issuer,
                algorithms=[jwt.ALGORITHMS.HS256],
                options={"require_sub": True},
            )
        except JWTError as err:
            raise InvalidToken(str(err))

    def encode_raw(self, data: dict) -> str:
        return jwt.encode(
            {**data, "iss": self._settings.jwt_issuer},
            self._settings.secret.get_secret_value(),
        )

    def decode(self, cls: Type[TokenType], token: str) -> TokenType:
        data = self.decode_raw(token)
        token_type = data.get("__token_type")
        if token_type is None:
            raise InvalidToken(
                "Malformed typed token: __token_type is not set"
            )
        if token_type not in (cls.__name__, cls.__token_type__):
            raise InvalidToken(
                f"Invalid token type: expected {cls.__name__} or"
                f' {cls.__token_type__}, got: "{token_type}"'
            )
        del data["__token_type"]
        try:
            return cls(**data)
        except ValidationError as err:
            raise InvalidToken(str(err))

    def encode(self, token_instance: TokenModel) -> str:
        data = token_instance.token_dict()
        data["__token_type"] = type(token_instance).__name__
        return self.encode_raw(data)


class SessionsService:
    def __init__(
        self,
        request: Request,
        response: Response,
        settings: Settings = Depends(get_settings),
        channel_layer: ChannelLayer = Depends(get_channel_layer),
    ):
        self._request = request
        self._settings = settings
        self._channel_layer = channel_layer
        self._response = response

    @staticmethod
    async def generate_session_id():
        session_id = secrets.token_urlsafe(20)
        while await UserSession.find({"_id": session_id}).exists():
            session_id = secrets.token_urlsafe(20)
        return session_id

    async def create(self, user: User):
        session = UserSession(
            id=await self.generate_session_id(),
            user_id=user.id,
            user_agent=self._request.headers.get("user-agent"),
            ip_address=self._request.client.host,
            is_superuser=user.is_superuser,
            expires_at=datetime.utcnow() + self._settings.session_lifetime,
            renew_at=datetime.utcnow()
            + self._settings.session_lifetime
            - timedelta(days=2),
        )
        await session.save()
        return session

    async def close(self, session: Union[UserSession, str]):
        if isinstance(session, str):
            session_id = session
            session = await UserSession.find_one({"_id": session})
        else:
            session_id = session.id
            session = session

        if session:
            await session.delete()
            await self._channel_layer.group_send(
                f"session/{session_id}",
                "force_refresh",
                {"reason": "session_closed"},
            )

    async def close_all_sessions(self, user_id: PydanticObjectId):
        sessions = await UserSession.find(
            UserSession.user_id == user_id
        ).to_list()
        for session in sessions:
            await self.close(session)

    def set_session(self, response: Response, session: UserSession):
        response.set_cookie(
            session_cookie.cookie,
            session.id,
            httponly=True,
            max_age=int(
                (session.expires_at - datetime.utcnow()).total_seconds()
            ),
            secure=self._settings.use_https,
            samesite=self._settings.cookies_policy,
        )

    async def renew(self, session: UserSession):
        new_session = UserSession(
            id=await self.generate_session_id(),
            user_id=session.user_id,
            user_agent=self._request.headers.get("user-agent"),
            ip_address=self._request.client.host,
            is_superuser=session.is_superuser,
            expires_at=datetime.utcnow() + self._settings.session_lifetime,
            renew_at=datetime.utcnow()
            + self._settings.session_lifetime
            - timedelta(days=2),
        )
        await new_session.insert()
        return new_session

    def set(self, session_id: str):
        self._response.set_cookie(
            session_cookie.cookie,
            session_id,
            httponly=True,
            max_age=int(self._settings.session_lifetime.total_seconds()),
            secure=self._settings.use_https,
            samesite=self._settings.cookies_policy,
        )


class UserService:
    def __init__(
        self,
        hashing_service: PasswordHashingService = Depends(),
        sessions_service: SessionsService = Depends(),
        settings: Settings = Depends(get_settings),
    ):
        self.hashing_service = hashing_service
        self.sessions_service = sessions_service
        self.settings = settings

    async def update_password(self, user: User, new_password: str):
        user.password_hash = self.hashing_service.hash_password(new_password)
        user.last_password_changed = datetime.utcnow()

    async def find_user_by_credentials(self, login: str, password: str):
        user = await User.find_one(
            {
                "$or": [
                    {"email": login},
                    {"normalized_username": login.upper()},
                ]
            },
            Eq("will_be_deleted_at", None),
        )
        if user and self.hashing_service.verify_password(
            password, user.password_hash
        ):
            return user
        return None

    async def create_user(
        self,
        username: str,
        plain_password: str,
        password_reset_required: bool,
        is_superuser: bool,
    ):
        return await User.create_user(
            username=username,
            password_hash=self.hashing_service.hash_password(plain_password),
            password_reset_required=password_reset_required,
            is_superuser=is_superuser,
        )

    async def create_default_user(self):
        return self.create_user(
            self.settings.default_username,
            self.settings.default_password,
            True,
            True,
        )

    async def deactivate_user(
        self, user: User, deactivation_timeout: Optional[timedelta] = None
    ) -> tuple[User, timedelta]:
        deactivation_timeout = (
            deactivation_timeout or self.settings.user_deactivation_timeout
        )
        await self.sessions_service.close_all_sessions(user.id)
        user.will_be_deleted_at = datetime.utcnow() + deactivation_timeout
        await user.save()
        return user, deactivation_timeout
