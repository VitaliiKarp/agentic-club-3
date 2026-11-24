from django.test import Client, TestCase

from .models import User


class AccountTests(TestCase):
    password = "Birds-dance-at-48"

    def test_register_login_logout_and_duplicate_email(self):
        registration = {
            "email": "  Demo@Example.org  ",
            "display_name": "Демо",
            "password1": self.password,
            "password2": self.password,
            "next": "https://example.net/",
        }
        response = self.client.post("/register/", registration)
        self.assertRedirects(response, "/")
        user = User.objects.get(email="demo@example.org")
        self.assertTrue(user.check_password(self.password))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertEqual(self.client.get("/logout/").status_code, 405)
        self.assertRedirects(self.client.post("/logout/"), "/")
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post("/register/", registration)
        self.assertTrue(response.context["form"].has_error("email"))
        self.assertEqual(User.objects.count(), 1)
        response = self.client.post("/login/", {
            "username": "DEMO@example.org", "password": self.password,
        })
        self.assertRedirects(response, "/")
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    def test_registration_requires_csrf(self):
        response = Client(enforce_csrf_checks=True).post("/register/", {})
        self.assertEqual(response.status_code, 403)
