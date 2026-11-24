from django.urls import path, re_path

from . import views

urlpatterns = [
    path("", views.catalog, name="catalog"),
    path("me/", views.profile, name="profile"),
    path("events/new/", views.create_event, name="event_create"),
    path("events/<int:event_id>/", views.detail, name="event_detail"),
    path("events/<int:event_id>/cover/", views.cover, name="event_cover"),
    path("events/<int:event_id>/edit/", views.edit_event, name="event_edit"),
    path("events/<int:event_id>/delete/", views.delete_event, name="event_delete"),
    path("events/<int:event_id>/participants/", views.participants, name="event_participants"),
    path("events/<int:event_id>/join/", views.join_event, name="event_join"),
    path("events/<int:event_id>/cancel/", views.cancel_registration, name="event_cancel"),
    path("events/<int:event_id>/comments/", views.add_comment, name="event_comment"),
    path("events/<int:event_id>/invite/", views.rotate_invitation, name="event_invite"),
    path("invite/continue/", views.continue_invitation, name="invite_continue"),
    re_path(r"^invite/(?P<token>[A-Za-z0-9_-]{43})/$", views.invitation, name="invitation"),
]
