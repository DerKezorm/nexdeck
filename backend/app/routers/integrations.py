"""Integrations: the adapter catalogue and configured connections."""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters import all_adapters, get_adapter
from ..adapters.base import AdapterError, Context
from ..deps import AdminUser, CurrentUser, DbSession, error, require_integration
from ..models import Integration, Role, Widget
from ..schemas import IntegrationCreate, IntegrationPatch, IntegrationTest
from ..services.collector import collector
from ..services.hass_ws import hass_listener
from ..services.integrations import public_config, resolve_config, store_config, validate_required

router = APIRouter(prefix="/api/v1", tags=["integrations"])

logger = logging.getLogger("nexdeck.integrations")


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
    logger.info("Connection %r (%s) added by %s%s%s.", integration.name, integration.kind, user.username,
                ", in demo mode" if integration.demo else "",
                ", reserved for administrators" if integration.admin_only else "")
    if integration.kind == "homeassistant":
        hass_listener.watch(integration.id)
    return _public(db, integration)


@router.patch("/integrations/{integration_id}", summary="Change an integration")
def patch_integration(integration_id: int, body: IntegrationPatch, user: AdminUser, db: DbSession) -> dict:
    integration = db.get(Integration, integration_id)
    if integration is None:
        raise error("not_found", "There is no such integration.", status.HTTP_404_NOT_FOUND)
    # ⚠️ What changed, never what it changed to: the config holds API keys.
    changed: list[str] = []
    if body.name is not None:
        if body.name.strip() != integration.name:
            changed.append(f"renamed from {integration.name!r}")
        integration.name = body.name.strip()
    if body.config is not None:
        integration.config = store_config(integration.kind, body.config, integration.config)
        changed.append("settings")
    if body.enabled is not None:
        if body.enabled != integration.enabled:
            changed.append("enabled" if body.enabled else "disabled")
        integration.enabled = body.enabled
    if body.demo is not None:
        if body.demo != integration.demo:
            changed.append("demo mode on" if body.demo else "demo mode off")
        integration.demo = body.demo
    if body.admin_only is not None:
        if body.admin_only != integration.admin_only:
            changed.append("reserved for administrators" if body.admin_only else "open to everyone")
        integration.admin_only = body.admin_only
    integration.last_error = ""
    db.commit()
    if changed:
        logger.info("Connection %r (%s): %s, by %s.", integration.name, integration.kind, "; ".join(changed), user.username)
    collector.reschedule_integration(integration.id)
    if integration.kind == "homeassistant":
        hass_listener.watch(integration.id)
    return _public(db, integration)


def _forget_in_options(db: Session, integration_id: int) -> int:
    """Take the deleted connection out of every option that names it.

    ⚠️ Connection numbers sit as bare integers inside ``Widget.options``, and
    SQLite hands out the number of a deleted row again. So the merged calendar
    of somebody who had picked connection 7 kept the 7, and the next connection
    an administrator created became connection 7: the card silently started
    reading a different service, one its owner may not even be allowed to see.
    Nothing pointed at it, because from the outside the card had not changed.
    """
    cleared = 0
    for widget in db.scalars(select(Widget)):
        options = dict(widget.options or {})
        touched = False
        for name, value in list(options.items()):
            if not isinstance(value, list):
                continue
            kept = [entry for entry in value if _not_this_connection(entry, integration_id)]
            if len(kept) != len(value):
                options[name] = kept
                touched = True
        if touched:
            widget.options = options
            cleared += 1
    return cleared


def _not_this_connection(entry: object, integration_id: int) -> bool:
    """Options carry the number as an int or as the text of one."""
    try:
        return int(entry) != integration_id  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a connection")
def delete_integration(integration_id: int, user: AdminUser, db: DbSession) -> None:
    """Widgets that used it stay and show that they need a connection."""
    integration = db.get(Integration, integration_id)
    if integration is None:
        raise error("not_found", "There is no such integration.", status.HTTP_404_NOT_FOUND)
    widget_ids = list(db.scalars(select(Widget.id).where(Widget.integration_id == integration.id)))
    name, kind = integration.name, integration.kind
    forgotten = _forget_in_options(db, integration.id)
    db.delete(integration)
    db.commit()
    # ⚠️ The cache and the client of a connection that no longer exists used
    # to sit in memory until the next restart, holding open sockets to a
    # service nobody asked about any more.
    collector.forget_integration(integration_id)
    logger.info("Connection %r (%s) deleted by %s; %d card(s) lose their service, %d option(s) cleared.",
                name, kind, user.username, len(widget_ids), forgotten)
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


@router.get("/integrations/{integration_id}/choices/{field}", summary="What a widget field can be set to, asked of the service")
async def field_choices(integration_id: int, field: str, user: CurrentUser, db: DbSession) -> list[dict[str, str]]:
    """Fills a dropdown whose answers live on the service, not in the code.

    ⚠️ Through ``require_integration``, like everything else that reaches a
    connection by a number out of a widget option. A connection reserved for
    administrators must not hand out its device names to anybody who can guess
    a number.
    """
    integration = require_integration(db, integration_id, user)
    try:
        adapter = get_adapter(integration.kind)
    except KeyError as failure:
        raise error("unknown_kind", f"There is no adapter {integration.kind!r}.") from failure
    ctx = Context(collector.client, integration_id=integration.id, cache={})
    try:
        offered = await adapter.choices(field, resolve_config(integration), ctx)
    except AdapterError as failure:
        raise error(failure.code, failure.message) from failure
    except Exception as failure:  # noqa: BLE001 - a dropdown must not take the sheet down
        logger.warning("Choices for %s.%s failed: %s", integration.kind, field, failure)
        raise error("choices_failed", "The service did not answer with a list.") from failure
    return [{"value": value, "label": label} for value, label in offered]


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
