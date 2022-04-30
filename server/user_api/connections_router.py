from uuid import UUID

from fastapi import APIRouter, HTTPException

from server.database import ConnectionInfo

connections_router = APIRouter(prefix="/connections")


@connections_router.get("/{connection_id}")
async def get_connection(connection_id: UUID):
    connection = await ConnectionInfo.get(connection_id)
    if connection is None:
        raise HTTPException(404, f"Connection {connection_id} not found")
    return connection
