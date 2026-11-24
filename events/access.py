from django.core.exceptions import PermissionDenied
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404

from .models import Event, EventAccess


def visibility_filter(user):
    public = Q(is_private=False)
    if not user.is_authenticated:
        return public
    grant = EventAccess.objects.filter(event_id=OuterRef("pk"), user_id=user.pk)
    return public | Q(author_id=user.pk) | Q(Exists(grant))


def event_cards(queryset):
    return queryset.annotate(booked=Count("participations"))


def visible_event(user, event_id, *, queryset=None):
    if queryset is None:
        queryset = Event.objects.all()
    return get_object_or_404(queryset.filter(visibility_filter(user)), pk=event_id)


def owned_event(user, event_id):
    event = visible_event(user, event_id)
    if event.author_id != user.pk:
        raise PermissionDenied
    return event
