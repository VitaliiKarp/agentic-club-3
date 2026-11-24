from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from .forms import LoginForm
from .views import register

urlpatterns = [
    path("register/", register, name="register"),
    path("login/", LoginView.as_view(
        template_name="accounts/auth.html", authentication_form=LoginForm,
    ), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
