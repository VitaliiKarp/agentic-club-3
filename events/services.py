import hashlib
import secrets

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from .access import owned_event, visibility_filter, visible_event
from .models import Comment, Event, EventAccess, EventCover, Participation


@transaction.atomic
def save_event(user, data, event_id=None):
    event = owned_event(user, event_id) if event_id else Event(author=user)
    starts_at = data["starts_at"]
    if starts_at != event.starts_at and starts_at <= timezone.now():
        raise ValidationError({"starts_at": "Виберіть час у майбутньому."})
    if event_id:
        minimum = event.participations.count()
        if data["capacity"] < minimum:
            raise ValidationError({"capacity": f"Уже записалося людей: {minimum}."})
    changed_visibility = event.is_private != data["is_private"]
    if changed_visibility:
        event.invite_digest = None
    event.title = data["title"]
    event.description = data["description"]
    event.starts_at = starts_at
    event.capacity = data["capacity"]
    event.is_private = data["is_private"]
    event.save()
    if event_id and changed_visibility:
        EventAccess.objects.filter(event=event).delete()
    if data["cover_file"] is not None:
        EventCover.objects.update_or_create(event=event, defaults={"content": data["cover_file"]})
    return event


@transaction.atomic
def delete_event(user, event_id):
    owned_event(user, event_id).delete()


@transaction.atomic
def join_event(user, event_id):
    event = visible_event(user, event_id)
    if event.participations.filter(user=user).exists():
        return "already_joined"
    if event.starts_at <= timezone.now():
        return "past"
    if event.participations.count() >= event.capacity:
        return "full"
    Participation.objects.create(event=event, user=user)
    return "joined"


@transaction.atomic
def cancel_registration(user, event_id):
    Participation.objects.filter(event_id=event_id, user=user).delete()
    return Event.objects.filter(visibility_filter(user), pk=event_id).exists()


@transaction.atomic
def add_comment(user, event_id, text):
    event = visible_event(user, event_id)
    Comment.objects.create(event=event, author=user, text=text)


def invitation_digest(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@transaction.atomic
def rotate_invitation(user, event_id):
    event = owned_event(user, event_id)
    if not event.is_private:
        raise Http404
    token = secrets.token_urlsafe(32)
    event.invite_digest = invitation_digest(token)
    event.save(update_fields=["invite_digest"])
    return token


@transaction.atomic
def accept_invitation(user, digest):
    if not digest:
        raise Http404
    event = Event.objects.filter(is_private=True, invite_digest=digest).first()
    if event is None:
        raise Http404
    EventAccess.objects.get_or_create(event=event, user=user)
    return event.pk
