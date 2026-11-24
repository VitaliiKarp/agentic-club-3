from django.contrib.auth import login
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.views.decorators.debug import sensitive_post_parameters

from .forms import RegistrationForm
from .models import User


@sensitive_post_parameters("password1", "password2")
@never_cache
@require_http_methods(["GET", "POST"])
def register(request):
    next_url = request.POST.get("next") if request.method == "POST" else request.GET.get("next")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
        next_url = ""
    if request.user.is_authenticated:
        return HttpResponseRedirect(next_url) if next_url else redirect("catalog")
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError:
            if not User.objects.filter(email=form.cleaned_data["email"]).exists():
                raise
            form.add_error("email", "Цей email уже зареєстрований.")
        else:
            login(request, user)
            return HttpResponseRedirect(next_url) if next_url else redirect("catalog")
    return render(request, "accounts/auth.html", {
        "form": form, "next": next_url, "registering": True,
    })
