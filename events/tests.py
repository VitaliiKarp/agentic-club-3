from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User

from . import services
from .models import Comment, Event, EventAccess, EventCover, Participation


def cover_upload():
    buffer = BytesIO()
    Image.new("RGBA", (16, 12), (30, 110, 180, 160)).save(buffer, "PNG")
    return SimpleUploadedFile("cover.png", buffer.getvalue(), content_type="image/png")


def event_form_data(title="Ігри в Києві", *, private=False, capacity=2):
    start = timezone.localtime(timezone.now() + timedelta(days=3))
    return {
        "title": title,
        "description": "Граємо разом.",
        "starts_at": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "capacity": capacity,
        "is_private": "1" if private else "0",
    }


class EventTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user("author@example.org", display_name="Автор")
        cls.guest = User.objects.create_user("visitor@example.org", display_name="Учасник")

    def setUp(self):
        self.owner_client = Client()
        self.owner_client.force_login(self.author)
        self.visitor = Client()
        self.visitor.force_login(self.guest)

    def create_event(self, *, title="Ігри в Києві", private=False, capacity=2):
        data = event_form_data(title, private=private, capacity=capacity)
        response = self.owner_client.post(reverse("event_create"), {**data, "cover_file": cover_upload()})
        if response.status_code != 302:
            self.fail(f"Creation failed: {response.context['form'].errors.as_json()}")
        event = Event.objects.get(title=title)
        self.assertRedirects(response, reverse("event_detail", args=[event.pk]))
        return event, data

    def invite(self, event):
        response = self.owner_client.post(reverse("event_invite", args=[event.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        return urlsplit(response.context["invite_url"]).path

    def test_public_catalog_search_and_cover(self):
        event, _ = self.create_event()
        self.create_event(title="Таємні ігри в Києві", private=True)
        Event.objects.create(
            author=self.author, title="Минулі події в Києві", description="Опис",
            starts_at=timezone.now() - timedelta(days=1), capacity=2,
        )
        response = self.client.get("/", {"q": "КИЄВІ"})
        self.assertContains(response, event.title)
        self.assertNotContains(response, "Таємні ігри")
        self.assertNotContains(response, "Минулі події")
        cover = self.client.get(reverse("event_cover", args=[event.pk]))
        self.assertEqual(cover["Content-Type"], "image/jpeg")
        self.assertIn("no-store", cover["Cache-Control"])
        with Image.open(BytesIO(cover.content)) as image:
            self.assertEqual(image.format, "JPEG")

    def test_rename_updates_catalog_search(self):
        event, data = self.create_event()
        edit = reverse("event_edit", args=[event.pk])
        self.assertRedirects(
            self.owner_client.post(edit, {**data, "title": "Прогулянка Львовом"}),
            reverse("event_detail", args=[event.pk]),
        )
        self.assertNotContains(self.client.get("/", {"q": "КИЄВІ"}), "Прогулянка Львовом")
        self.assertContains(self.client.get("/", {"q": "ЛЬВОВОМ"}), "Прогулянка Львовом")

    def test_join_comment_cancel_and_author_participants(self):
        event, _ = self.create_event(capacity=1)
        pk = [event.pk]
        detail = reverse("event_detail", args=pk)
        join = reverse("event_join", args=pk)
        self.assertEqual(self.visitor.get(join).status_code, 405)
        self.assertRedirects(self.visitor.post(join), detail)
        self.assertRedirects(self.visitor.post(join), detail)
        self.assertEqual(Participation.objects.filter(event=event).count(), 1)
        self.assertContains(self.visitor.get(detail), "Вільних місць: 0 з 1")
        self.assertContains(self.visitor.get("/me/"), event.title)
        participants = self.owner_client.get(reverse("event_participants", args=pk))
        self.assertContains(participants, self.guest.public_name)
        self.assertNotContains(participants, self.guest.email)
        full = self.owner_client.post(join, follow=True)
        self.assertContains(full, "Місць немає.")
        comment = reverse("event_comment", args=pk)
        self.assertEqual(self.visitor.post(comment, {"text": "  "}).status_code, 400)
        self.assertRedirects(self.visitor.post(comment, {"text": "До зустрічі!"}), detail)
        self.assertContains(self.client.get(detail), "До зустрічі!")
        cancel = reverse("event_cancel", args=pk)
        self.assertRedirects(self.visitor.post(cancel), detail)
        self.assertRedirects(self.visitor.post(cancel), detail)
        self.assertEqual(event.participations.count(), 0)
        self.assertNotContains(self.visitor.get("/me/"), event.title)

    def test_private_access_rotation_and_profile(self):
        event, _ = self.create_event(title="Закрита зустріч", private=True)
        pk = [event.pk]
        detail = reverse("event_detail", args=pk)
        cover = reverse("event_cover", args=pk)
        old_invite = self.invite(event)
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.visitor.get(cover).status_code, 404)
        self.assertEqual(self.visitor.post(reverse("event_join", args=pk)).status_code, 404)
        self.assertEqual(self.visitor.post(reverse("event_comment", args=pk), {"text": "Привіт"}).status_code, 404)
        self.assertNotContains(self.visitor.get(old_invite), event.title)
        self.assertFalse(EventAccess.objects.filter(event=event, user=self.guest).exists())
        new_invite = self.invite(event)
        self.assertEqual(self.visitor.post(old_invite).status_code, 404)
        self.assertRedirects(self.visitor.post(new_invite), detail)
        self.assertRedirects(self.visitor.post(new_invite), detail)
        self.assertEqual(EventAccess.objects.filter(event=event, user=self.guest).count(), 1)
        self.assertEqual(self.visitor.get(cover).status_code, 200)
        self.assertRedirects(self.visitor.post(reverse("event_join", args=pk)), detail)
        self.assertContains(self.visitor.get("/me/"), event.title)
        self.invite(event)
        self.assertEqual(self.visitor.get(detail).status_code, 200)
        self.assertEqual(self.visitor.post(reverse("event_invite", args=pk)).status_code, 403)

    def test_invitation_survives_registration_without_disclosing_details(self):
        event, _ = self.create_event(title="Запрошені", private=True)
        invite = self.invite(event)
        response = self.client.get(invite)
        self.assertNotContains(response, event.title)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        continuation = reverse("invite_continue")
        password = "Fresh-window-at-52"
        response = self.client.post("/register/", {
            "email": "new@example.org", "password1": password, "password2": password,
            "next": continuation,
        })
        self.assertRedirects(response, continuation)
        detail = reverse("event_detail", args=[event.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertRedirects(self.client.post(continuation), detail)
        self.client.post("/logout/")
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(detail).status_code, 404)

    def test_only_author_manages_event(self):
        event, data = self.create_event()
        for route in ("event_edit", "event_delete", "event_participants"):
            self.assertEqual(self.visitor.get(reverse(route, args=[event.pk])).status_code, 403)
        response = self.visitor.post(reverse("event_edit", args=[event.pk]), {**data, "title": "Інша назва"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.visitor.post(reverse("event_delete", args=[event.pk])).status_code, 403)
        event.refresh_from_db()
        self.assertNotEqual(event.title, "Інша назва")

    def test_visibility_change_redacts_profile_and_allows_cancellation(self):
        event, data = self.create_event(title="Нове приватне ім’я")
        self.visitor.post(reverse("event_join", args=[event.pk]))
        details = reverse("event_detail", args=[event.pk])
        edit = reverse("event_edit", args=[event.pk])
        self.assertRedirects(self.owner_client.post(edit, {**data, "is_private": "1"}), details)
        response = self.visitor.get("/me/")
        self.assertContains(response, "Приватна подія")
        self.assertNotContains(response, event.title)
        self.assertNotContains(response, reverse("event_cover", args=[event.pk]))
        cancel = reverse("event_cancel", args=[event.pk])
        self.assertRedirects(self.visitor.post(cancel), "/me/")
        self.assertFalse(event.participations.exists())

    def test_reopening_to_public_removes_previous_private_access(self):
        event, data = self.create_event(private=True)
        old_invite = self.invite(event)
        self.visitor.post(old_invite)
        edit = reverse("event_edit", args=[event.pk])
        detail = reverse("event_detail", args=[event.pk])
        self.assertRedirects(self.owner_client.post(edit, {**data, "is_private": "0"}), detail)
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertFalse(EventAccess.objects.filter(event=event).exists())
        self.assertRedirects(self.owner_client.post(edit, data), detail)
        self.assertEqual(self.visitor.get(detail).status_code, 404)
        self.assertEqual(self.visitor.post(old_invite).status_code, 404)

    def test_failed_edit_keeps_existing_event_and_cover(self):
        event, data = self.create_event()
        for client in (self.owner_client, self.visitor):
            client.post(reverse("event_join", args=[event.pk]))
        edit = reverse("event_edit", args=[event.pk])
        stored_cover = event.cover.content
        response = self.owner_client.post(edit, {**data, "capacity": 1, "title": "Зміна"})
        self.assertTrue(response.context["form"].has_error("capacity"))
        upload = SimpleUploadedFile("cover.png", b"not a picture", content_type="image/png")
        response = self.owner_client.post(edit, {**data, "cover_file": upload})
        self.assertTrue(response.context["form"].has_error("cover_file"))
        self.assertEqual(EventCover.objects.get(event=event).content, stored_cover)
        self.assertEqual(Event.objects.get(pk=event.pk).title, event.title)

    def test_past_event_rejects_new_user_but_allows_unchanged_date_on_edit(self):
        event, data = self.create_event()
        event.starts_at = (timezone.now() - timedelta(days=1)).replace(microsecond=0)
        event.save(update_fields=["starts_at"])
        response = self.visitor.post(reverse("event_join", args=[event.pk]), follow=True)
        self.assertContains(response, "Подія вже почалася.")
        self.assertFalse(event.participations.exists())
        data["starts_at"] = timezone.localtime(event.starts_at).strftime("%Y-%m-%dT%H:%M:%S")
        data["description"] = "Оновлений опис"
        response = self.owner_client.post(reverse("event_edit", args=[event.pk]), data)
        self.assertRedirects(response, reverse("event_detail", args=[event.pk]))
        event.refresh_from_db()
        self.assertEqual(event.description, "Оновлений опис")

    def test_delete_removes_related_data_and_invite(self):
        event, _ = self.create_event(private=True)
        invite = self.invite(event)
        self.visitor.post(invite)
        self.visitor.post(reverse("event_join", args=[event.pk]))
        self.visitor.post(reverse("event_comment", args=[event.pk]), {"text": "Привіт"})
        self.assertRedirects(self.owner_client.post(reverse("event_delete", args=[event.pk])), "/me/")
        self.assertEqual(self.visitor.get(invite).status_code, 404)
        self.assertEqual(self.visitor.get(reverse("event_detail", args=[event.pk])).status_code, 404)
        for related in (Participation, EventAccess, EventCover, Comment):
            self.assertFalse(related.objects.filter(event=event).exists())


class CapacityTests(TransactionTestCase):
    def setUp(self):
        self.author = User.objects.create_user("owner@example.org")
        self.first = User.objects.create_user("first@example.org")
        self.second = User.objects.create_user("second@example.org")
        self.event = Event.objects.create(
            author=self.author, title="Подія", description="Опис",
            starts_at=timezone.now() + timedelta(days=1), capacity=2,
        )

    def race(self, *actions):
        start = Barrier(len(actions), timeout=5)

        def perform(action):
            try:
                start.wait()
                return action()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(actions)) as executor:
            return list(executor.map(perform, actions))

    def test_one_of_two_users_takes_last_seat(self):
        Participation.objects.create(event=self.event, user=self.author)
        outcomes = self.race(
            lambda: services.join_event(self.first, self.event.pk),
            lambda: services.join_event(self.second, self.event.pk),
        )
        self.assertCountEqual(outcomes, ["joined", "full"])
        self.assertEqual(self.event.participations.count(), 2)

    def test_join_and_capacity_decrease_are_serialized(self):
        Participation.objects.create(event=self.event, user=self.first)

        def reduce_capacity():
            try:
                services.save_event(self.author, {
                    "title": self.event.title, "description": self.event.description,
                    "starts_at": self.event.starts_at, "capacity": 1,
                    "is_private": False, "cover_file": None,
                }, self.event.pk)
            except ValidationError:
                return "rejected"
            return "updated"

        joined, edited = self.race(
            lambda: services.join_event(self.second, self.event.pk), reduce_capacity,
        )
        self.event.refresh_from_db()
        self.assertIn((joined, edited), [("joined", "rejected"), ("full", "updated")])
        self.assertLessEqual(self.event.participations.count(), self.event.capacity)
