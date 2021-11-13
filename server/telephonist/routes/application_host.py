from datetime import datetime, timedelta
from typing import Optional

from fastapi import Body, HTTPException, Depends
from pydantic import BaseModel
from starlette import status
from starlette.requests import Request

from server.auth.models import TokenModel
from server.auth.utils import TokenDependency, UserToken
from server.telephonist.models import ApplicationHost, HostSoftware, LocalConfig, Server
from server.telephonist.models.security_code import AppHostSecurityCode
from server.telephonist.routes._router import router

application_host_token = TokenDependency(subject=ApplicationHost, required=True)


async def application_host(token: TokenModel = application_host_token) -> ApplicationHost:
    host = await ApplicationHost.get(token.sub.oid)
    if host is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return host


class HostedApplication(BaseModel):
    name: str


class HostUpdate(BaseModel):
    local_config: LocalConfig
    software: Optional[HostSoftware]


def apply_host_update(host: ApplicationHost, update: HostUpdate):
    if update.software:
        host.software = update.software

    if update.local_config:
        host.local_config = update.local_config


@router.post('/app-host/update')
async def host_update(
        host: ApplicationHost = Depends(application_host),
        body: HostUpdate = Body(...)
):
    apply_host_update(host, body)
    await host.save_changes()


@router.post('/app-host/self-register')
async def self_registration():
    code = await AppHostSecurityCode.new()
    return {'code': code}


class SelfRegistrationCode(BaseModel):
    code: str


@router.post('/app-host/self-register/confirm')
async def confirm_self_registration(
        body: SelfRegistrationCode,
        user_token: TokenModel = UserToken()
):
    code = await AppHostSecurityCode.get_valid_code(body.code)
    if code is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Code is invalid')
    code.expires_at = datetime.utcnow() + timedelta(days=1)
    code.confirmed = True
    await code.save()
    # TODO log


class FinishSelfRegistration(SelfRegistrationCode):
    name: str
    update: Optional[HostUpdate]


@router.post('/app-host/self-register/finish')
async def finish_self_registration(
        body: FinishSelfRegistration,
        request: Request
):
    code = await AppHostSecurityCode.get_valid_code(body.code)
    if code is None or not code.confirmed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Code does not exist, expired or wasn\'t confirmed yet')
    await Server.report_server(request.client)
    host = ApplicationHost(name=body.name)
    if body.update:
        apply_host_update(host, body.update)
    await host.save_changes()
    return host.dict(exclude={'token'})


class AppHostToken(BaseModel):
    token: str


@router.post('/app-host/token', name='Get application-host access token')
async def authenticate_host(body: AppHostToken):
    host = await ApplicationHost.find_one(ApplicationHost.token == body.token)
    if host is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'App host with given could\'nt be found')
    token = host.create_token(lifetime=timedelta(hours=2))
    return {'token': token.encode()}
