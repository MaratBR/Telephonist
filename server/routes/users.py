from fastapi import APIRouter, Depends

from server.internal.auth.dependencies import UserToken
from server.models.auth import User, UserView
from server.models.common import Pagination

users_router = APIRouter(prefix="/users")


class UsersPagination(Pagination):
    ordered_by_options = {"username", "_id"}


@users_router.get("", dependencies=[UserToken()])
async def get_users(args: UsersPagination = Depends()):
    return await args.paginate(User, UserView)
