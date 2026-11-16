"""Read-only communication with the optional host update agent."""

from pathlib import Path

import httpx


def read_agent_status(
    socket_path: Path,
    token: str,
    deployment_id: str,
) -> dict:
    """Return a verified status, or fail closed."""

    disabled = {
        "available": False,
        "deployment": "unknown",
        "can_update": False,
        "reason": "agent_unreachable",
    }

    if not token or not deployment_id:
        return {
            **disabled,
            "reason": "agent_configuration_incomplete",
        }

    try:
        transport = httpx.HTTPTransport(uds=str(socket_path))

        with httpx.Client(
            transport=transport,
            timeout=2.0,
        ) as client:
            response = client.get(
                "http://update-agent/v1/status",
                headers={
                    "Authorization": f"Bearer {token}",
                },
            )
            if response.status_code in (401, 403):
                return {**disabled, "reason": "agent_auth_failed"}

            response.raise_for_status()
            payload = response.json()

    except (httpx.HTTPError, ValueError, OSError):
        return disabled

    if not isinstance(payload, dict):
        return {
            **disabled,
            "reason": "agent_invalid_response",
        }

    if (
        not isinstance(payload.get("deployment_id"), str)
        or type(payload.get("available")) is not bool
        or type(payload.get("can_update")) is not bool
    ):
        return {**disabled, "reason": "agent_invalid_response"}

    if payload.get("deployment_id") != deployment_id:
        return {
            **disabled,
            "reason": "deployment_mismatch",
        }

    if payload.get("available") is not True:
        return {
            **disabled,
            "reason": "agent_unavailable",
        }

    return {
        "available": True,
        "deployment": deployment_id,
        "can_update": payload.get("can_update") is True,
        "reason": "ready",
        "stage": payload.get("stage", "idle"),
        "error": payload.get("error"),
    }



def request_agent_install(
    socket_path: Path,
    token: str,
    deployment_id: str,
    backup_filename: str,
) -> dict:
    """Request installation through the authenticated host agent."""

    if not token or not deployment_id or not backup_filename:
        raise ValueError("Incomplete updater request")

    transport = httpx.HTTPTransport(uds=str(socket_path))

    try:
        with httpx.Client(transport=transport, timeout=15.0) as client:
            response = client.post(
                "http://update-agent/v1/install",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "deployment_id": deployment_id,
                    "backup": backup_filename,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise RuntimeError(
            "Host updater did not accept installation"
        ) from exc

    if (
        response.status_code != 202
        or not isinstance(payload, dict)
        or payload.get("status") != "accepted"
    ):
        raise RuntimeError(
            "Unexpected host updater response"
        )

    return payload
