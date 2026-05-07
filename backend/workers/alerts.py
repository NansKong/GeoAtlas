from __future__ import annotations

import logging
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

from core.config import settings
from modules.boards.models import Alert, AlertNotification
from modules.events.models import Event, EventImpact, EventStatus
from modules.market.models import Asset
from modules.users.models import User
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

PUBLISHED_EVENT_STATUSES = {EventStatus.AUTO_APPROVED, EventStatus.HUMAN_APPROVED}


def _send_email(user: User, event: Event, asset_labels: list[str]) -> tuple[bool, str | None]:
    if not settings.SENDGRID_API_KEY or not user.email:
        return False, "sendgrid_not_configured"

    payload = {
        "personalizations": [{"to": [{"email": user.email}]}],
        "from": {"email": settings.FROM_EMAIL},
        "subject": f"GeoAtlas alert: {event.title}",
        "content": [
            {
                "type": "text/plain",
                "value": (
                    f"Event: {event.title}\n"
                    f"Type: {event.event_type.value}\n"
                    f"Country: {event.country or 'n/a'}\n"
                    f"Affected assets: {', '.join(asset_labels) if asset_labels else 'n/a'}\n"
                    f"Confidence: {event.confidence_score if event.confidence_score is not None else 'n/a'}"
                ),
            }
        ],
    }
    try:
        response = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        return True, None
    except Exception as exc:
        return False, str(exc)


def _send_web_push(user: User, event: Event) -> tuple[bool, str | None]:
    tokens = (user.alert_preferences or {}).get("web_push_tokens") or []
    if not settings.FCM_SERVER_KEY or not tokens:
        return False, "fcm_not_configured"

    payload = {
        "registration_ids": tokens,
        "notification": {
            "title": f"GeoAtlas: {event.event_type.value.replace('_', ' ')}",
            "body": event.title,
        },
        "data": {
            "event_id": str(event.id),
            "event_type": event.event_type.value,
        },
    }
    try:
        response = httpx.post(
            "https://fcm.googleapis.com/fcm/send",
            headers={
                "Authorization": f"key={settings.FCM_SERVER_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        return True, None
    except Exception as exc:
        return False, str(exc)


def _notification_exists(session: Session, *, alert_id, event_id, channel: str) -> bool:
    existing = session.execute(
        select(AlertNotification.id).where(
            AlertNotification.alert_id == alert_id,
            AlertNotification.event_id == event_id,
            AlertNotification.channel == channel,
        )
    ).scalar_one_or_none()
    return existing is not None


@celery_app.task(name="workers.alerts.evaluate_event_alerts", bind=True, max_retries=2)
def evaluate_event_alerts(self, event_id: str):
    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    event_uuid = uuid.UUID(event_id)

    with Session(engine) as session:
        event = session.get(Event, event_uuid)
        if not event or event.status not in PUBLISHED_EVENT_STATUSES:
            return {"event_id": event_id, "status": "ignored"}

        impacts = session.execute(
            select(EventImpact, Asset)
            .join(Asset, Asset.id == EventImpact.asset_id)
            .where(EventImpact.event_id == event.id)
        ).all()
        impact_by_asset_id = {impact.asset_id: impact for impact, _ in impacts}
        asset_labels = [asset.ticker for _, asset in impacts]

        alerts = session.execute(
            select(Alert, User)
            .join(User, User.id == Alert.user_id)
            .where(Alert.is_active.is_(True))
        ).all()

        matched = 0
        delivered = 0
        for alert, user in alerts:
            if alert.event_type and alert.event_type != event.event_type.value:
                continue

            matched_impact = None
            if alert.asset_id is not None:
                matched_impact = impact_by_asset_id.get(alert.asset_id)
                if matched_impact is None:
                    continue

            signal_strength = 0.0
            if matched_impact is not None:
                signal_strength = float(
                    matched_impact.impact_strength
                    or matched_impact.confidence_score
                    or event.confidence_score
                    or 0.0
                )
            else:
                signal_strength = float(event.confidence_score or 0.0)

            if alert.threshold is not None and signal_strength < float(alert.threshold):
                continue

            matched += 1
            preferences = user.alert_preferences or {}
            for channel, sender in (("email", _send_email), ("web_push", _send_web_push)):
                if channel == "email" and not preferences.get("email_enabled", True):
                    continue
                if channel == "web_push" and not preferences.get("web_push_enabled", False):
                    continue
                if _notification_exists(session, alert_id=alert.id, event_id=event.id, channel=channel):
                    continue

                notification = AlertNotification(
                    alert_id=alert.id,
                    user_id=user.id,
                    event_id=event.id,
                    channel=channel,
                    status="queued",
                    delivered=False,
                )
                try:
                    with session.begin_nested():
                        session.add(notification)
                        session.flush()
                except IntegrityError:
                    continue

                ok, error_message = sender(user, event, asset_labels) if channel == "email" else sender(user, event)
                notification.delivered = ok
                notification.status = "delivered" if ok else "skipped"
                notification.error_message = error_message
                if ok:
                    delivered += 1

        session.commit()

    result = {"event_id": event_id, "matched_alerts": matched, "delivered_notifications": delivered}
    logger.info("Evaluated event alerts: %s", result)
    return result
