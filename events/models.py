import unicodedata

from django.conf import settings
from django.db import models


def search_key(value):
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", value).casefold())


class Event(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField("Назва", max_length=120)
    title_key = models.TextField(editable=False)
    description = models.TextField("Опис", max_length=3000)
    starts_at = models.DateTimeField("Дата й час початку")
    capacity = models.PositiveIntegerField("Кількість місць")
    is_private = models.BooleanField(default=False)
    invite_digest = models.CharField(max_length=64, null=True, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gte=1, capacity__lte=1000),
                name="event_capacity_in_range",
            ),
            models.CheckConstraint(
                condition=models.Q(is_private=True) | models.Q(invite_digest__isnull=True),
                name="event_invite_only_for_private",
            ),
        ]
        indexes = [models.Index(fields=["is_private", "starts_at"], name="event_catalog_order")]

    def save(self, *args, **kwargs):
        self.title_key = search_key(self.title)
        if kwargs.get("update_fields") is not None and "title" in kwargs["update_fields"]:
            kwargs["update_fields"] = {*kwargs["update_fields"], "title_key"}
        return super().save(*args, **kwargs)

    @property
    def remaining(self):
        return self.capacity - self.booked


class EventCover(models.Model):
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name="cover")
    content = models.BinaryField()


class Participation(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="participations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="participation_once_per_user"),
        ]


class EventAccess(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="access_grants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="access_once_per_user"),
        ]


class Comment(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
