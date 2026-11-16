"""Administrator-only interface for the optional host update agent."""

import asyncio

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..deps import AdminUser
from ..services.update_agent import read_agent_status, request_agent_install
from ..services import backup

router = APIRouter(prefix="/api/v1/self-update", tags=["admin"])


@router.get("/status", summary="Read self-update availability")
def update_status(admin: AdminUser) -> dict:
    """Report configuration without contacting Docker or executing commands."""
    settings = get_settings()
    socket = settings.update_agent_socket
    token = settings.update_agent_token

    if socket is None:
        return {
            "configured": False,
            "available": False,
            "deployment": "unknown",
            "can_update": False,
            "reason": "agent_not_configured",
        }

    deployment_id = settings.update_deployment_id

    if not token or not deployment_id:
        return {
            "configured": False,
            "available": False,
            "deployment": "unknown",
            "can_update": False,
            "reason": "agent_configuration_incomplete",
        }

    agent_status = read_agent_status(socket, token, deployment_id)

    return {
        "configured": True,
        **agent_status,
    }


@router.post("/install", summary="Prepare a NexDeck update")
async def install_update(admin: AdminUser) -> dict:
    """Require an enrolled updater and create a pre-update restore point.

    No Docker operations are performed by this endpoint yet.
    """
    settings = get_settings()

    if (
        settings.update_agent_socket is None
        or not settings.update_agent_token
        or not settings.update_deployment_id
    ):
        raise HTTPException(
            status_code=503,
            detail="Host updater is not configured",
        )

    agent = read_agent_status(
        settings.update_agent_socket,
        settings.update_agent_token,
        settings.update_deployment_id,
    )

    if not agent.get("can_update"):
        raise HTTPException(
            status_code=503,
            detail="Host updater is not ready",
        )

    try:
        path = await asyncio.to_thread(
            backup.create,
            kind=backup.MANUAL,
            note="Pre-update restore point",
        )
    except backup.BackupError as exc:
        raise HTTPException(
            status_code=500,
            detail="Pre-update backup failed",
        ) from exc

    try:
        result = await asyncio.to_thread(
            request_agent_install,
            settings.update_agent_socket,
            settings.update_agent_token,
            settings.update_deployment_id,
            path.name,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Host updater did not accept installation",
        ) from exc

    return {
        "status": result["status"],
        "backup": path.name,
        "installation_started": True,
    }
