from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
from django.views.decorators.http import require_safe


@require_safe
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz/", health, name="health"),
    path("", include("accounts.urls")),
    path("", include("events.urls")),
]
