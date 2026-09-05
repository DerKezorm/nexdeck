"""Integrations: the adapter catalogue and configured connections."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import func, select

from ..adapters import all_adapters, get_adapter
from ..adapters.base import AdapterError, Context
from ..deps import AdminUser, CurrentUser, DbSession, error
from ..models import Integration, Role, Widget
from ..schemas import IntegrationCreate, IntegrationPatch, IntegrationTest
from ..services.collector import collector
from ..services.hass_ws import hass_listener
from ..services.integrations import public_config, resolve_config, store_config, validate_required

router = APIRouter(prefix="/api/v1", tags=["integrations"])


@router.get("/adapters", summary="List every adapter and its widgets")
def adapters(user: CurrentUser) -> list[dict]:
    return [a.to_dict() for a in all_adapters()]


def _public(db: DbSession, integration: Integration) -> dict:
    widgets = db.scalar(select(func.count(Widget.id)).where(Widget.integration_id == integration.id)) or 0
    adapter = get_adapter(integration.kind)
    return {
        "id": integration.id, "kind": integration.kind, "label": adapter.label, "icon": adapter.icon, "beta": adapter.beta,
        "name": integration.name, "config": public_config(integration), "enabled": integration.enabled, "demo": integration.demo,
        "last_ok_at": integration.last_ok_at, "last_error": integration.last_error, "widget_count": int(widgets),
        "admin_only": integration.admin_only,
        "created_at": integration.created_at,
    }


@router.get("/integrations", summary="List configured integrations")
def list_integrations(user: CurrentUser, db: DbSession) -> list[dict]:
    """Secrets never leave the server; the API says only whether one is set.

    A locked connection is left out for everyone but administrators: its cards
    still run on a board that was shared, but nobody else builds new ones from
    it, and it is not in the catalogue they choose from.
    """
    rows = db.scalars(select(Integration).order_by(Integration.name))
    admin = user.role == Role.admin.value
    return [_public(db, i) for i in rows if admin or not i.admin_only]


@router.post("/integrations", status_code=status.HTTP_201_CREATED, summary="Add an integration")
def create_integration(body: IntegrationCreate, user: AdminUser, db: DbSession) -> dict:
    try:
        get_adapter(body.kind)
    except KeyError as failure:
        raise error("unknown_kind", f"There is no adapter {body.kind!r}.") from failure
    config = store_config(body.kind, body.config)
    if not body.demo:
        missing = validate_required(body.kind, config)
        if missing:
            raise error("missing_fields", f"Required fields are missing: {', '.join(missing)}.")
    integration = Integration(kind=body.kind, name=body.name.strip(), config=config, enabled=body.enabled, demo=body.demo,
                              admin_only=body.admin_only, created_by=user.id)
    db.add(integration)
    db.commit()
    if integration.kind == "homeassistant":
        hass_listener.watch(integration.id)
    return _public(db, integration)


@router.patch("/integrations/{integration_id}", summary="Change an integration")
def patch_integration(integration_id: int, body: IntegrationPatch, user: AdminUser, db: DbSession) -> dict:
    integration = db.get(Integration, integration_id)
    if integration is None:
        raise error("not_found", "There is no such integration.", status.HTTP_404_NOT_FOUND)
    if body.name is not None:
        integration.name = body.name.strip()
    if body.config is not None:
        integration.config = store_config(integration.kind, body.config, integration.config)
    if body.enabled is not None:
        integration.enabled = body.enabled
    if body.demo is not None:
        integration.demo = body.demo
    if body.admin_only is not None:
        integration.admin_only = body.admin_only
    integration.last_error = ""
    db.commit()
    collector.reschedule_integration(integration.id)
    if integration.kind == "homeassistant":
        hass_listener.watch(integration.id)
    return _public(db, integration)


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an integration")
def delete_integration(integration_id: int, user: AdminUser, db: DbSession) -> None:
    """Widgets that used it stay and show that they need a connection."""
    integration = db.get(Integration, integration_id)
    if integration is None:
        raise error("not_found", "There is no such integration.", status.HTTP_404_NOT_FOUND)
    widget_ids = list(db.scalars(select(Widget.id).where(Widget.integration_id == integration.id)))
    db.delete(integration)
    db.commit()
    hass_listener.unwatch(integration_id)
    for widget_id in widget_ids:
        collector.schedule(widget_id)


@router.post("/integrations/test", summary="Test a connection before saving it")
async def test_integration(body: IntegrationTest, user: AdminUser, db: DbSession) -> dict:
    """Empty secret fields fall back to the stored values of ``integration_id``."""
    try:
        adapter = get_adapter(body.kind)
    except KeyError as failure:
        raise error("unknown_kind", f"There is no adapter {body.kind!r}.") from failure
    existing = db.get(Integration, body.integration_id) if body.integration_id else None
    stored = store_config(body.kind, body.config, existing.config if existing and existing.kind == body.kind else None)
    probe = Integration(kind=body.kind, name="probe", config=stored)
    config = resolve_config(probe)
    missing = validate_required(body.kind, config)
    if missing:
        raise error("missing_fields", f"Required fields are missing: {', '.join(missing)}.")
    ctx = Context(collector.client, integration_id=existing.id if existing else None, cache={})
    try:
        message = await adapter.test(config, ctx)
    except AdapterError as failure:
        return {"ok": False, "message": failure.message, "hint": failure.hint, "code": failure.code}
    except Exception as failure:  # noqa: BLE001
        return {"ok": False, "message": f"Unexpected error: {failure.__class__.__name__}.", "hint": "", "code": "crash"}
    return {"ok": True, "message": message}


@router.post("/integrations/{integration_id}/test", summary="Test a saved integration")
async def test_saved(integration_id: int, user: AdminUser, db: DbSession) -> dict:
    integration = db.get(Integration, integration_id)
    if integration is None:
        raise error("not_found", "There is no such integration.", status.HTTP_404_NOT_FOUND)
    if integration.demo:
        return {"ok": True, "message": "Demo mode: nothing is contacted."}
    adapter = get_adapter(integration.kind)
    ctx = Context(collector.client, integration_id=integration.id, cache={})
    try:
        message = await adapter.test(resolve_config(integration), ctx)
    except AdapterError as failure:
        integration.last_error = failure.message
        db.commit()
        return {"ok": False, "message": failure.message, "hint": failure.hint, "code": failure.code}
    integration.last_error = ""
    db.commit()
    return {"ok": True, "message": message}
