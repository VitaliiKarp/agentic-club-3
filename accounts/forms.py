from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User, normalize_email


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="Email", max_length=254)

    class Meta:
        model = User
        fields = ("email", "display_name")

    def clean_email(self):
        return normalize_email(self.cleaned_data["email"])


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "username"}),
    )
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Перевірте email і пароль та спробуйте ще раз.",
        "inactive": "Перевірте email і пароль та спробуйте ще раз.",
    }
