from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import BooleanField, Case, Exists, OuterRef, Subquery, Value, When
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_safe
from django.views.decorators.debug import sensitive_variables

from . import services
from .access import event_cards, owned_event, visibility_filter, visible_event
from .forms import CommentForm, EventForm
from .models import Comment, Event, Participation, search_key

INVITATION_SESSION_KEY = "pending_event_invitation"


def login_for_event_action(view):
    @wraps(view)
    def wrapped(request, event_id):
        if request.user.is_authenticated:
            return view(request, event_id)
        destination = (
            reverse("profile") if request.POST.get("return_to") == "profile"
            else reverse("event_detail", args=[event_id])
        )
        messages.info(request, "Увійдіть та повторіть дію.")
        return redirect_to_login(destination)
    return wrapped


@require_safe
def catalog(request):
    term = request.GET.get("q", "").strip()[:120]
    events = Event.objects.filter(is_private=False, starts_at__gt=timezone.now())
    if term:
        events = events.filter(title_key__contains=search_key(term))
    events = event_cards(events).order_by("starts_at", "pk")
    page = Paginator(events, 12).get_page(request.GET.get("page"))
    return render(request, "events/catalog.html", {"page": page, "query": term})


def render_detail(request, event, comment_form=None, status=200):
    now = timezone.now()
    accessible = Event.objects.filter(visibility_filter(request.user), pk=event.pk)
    comments = Comment.objects.filter(event__in=accessible).select_related("author").order_by("-pk")
    booked = request.user.is_authenticated and event.participations.filter(user=request.user).exists()
    return render(request, "events/detail.html", {
        "event": event,
        "booked": booked,
        "started": event.starts_at <= now,
        "owner": request.user.is_authenticated and event.author_id == request.user.pk,
        "page": Paginator(comments, 20).get_page(request.GET.get("page")),
        "comment_form": comment_form if comment_form is not None else CommentForm(),
    }, status=status)


@require_safe
def detail(request, event_id):
    event = visible_event(request.user, event_id, queryset=event_cards(Event.objects.all()))
    return render_detail(request, event)


@require_safe
def cover(request, event_id):
    _, content = get_object_or_404(
        Event.objects.filter(visibility_filter(request.user)).values_list("pk", "cover__content"),
        pk=event_id,
    )
    if content is None:
        return FileResponse((settings.BASE_DIR / "static" / "hero.jpg").open("rb"), content_type="image/jpeg")
    return HttpResponse(content, content_type="image/jpeg")


def render_event_form(request, event=None):
    form = EventForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        instance=event,
    )
    if request.method == "POST" and form.is_valid():
        try:
            saved = services.save_event(request.user, form.cleaned_data, event.pk if event else None)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Зміни збережено." if event else "Подію створено.")
            return redirect("event_detail", event_id=saved.pk)
    return render(request, "events/form.html", {"form": form, "editing": event is not None})


@require_http_methods(["GET", "POST"])
@login_required
def create_event(request):
    return render_event_form(request)


@require_http_methods(["GET", "POST"])
@login_required
def edit_event(request, event_id):
    return render_event_form(request, owned_event(request.user, event_id))


@require_http_methods(["GET", "POST"])
@login_required
def delete_event(request, event_id):
    if request.method == "POST":
        services.delete_event(request.user, event_id)
        messages.success(request, "Подію видалено.")
        return redirect("profile")
    event = owned_event(request.user, event_id)
    return render(request, "events/delete.html", {"event": event})


@require_safe
@login_required
def participants(request, event_id):
    event = owned_event(request.user, event_id)
    enrollment = event.participations.select_related("user").order_by("created_at", "pk")
    return render(request, "events/participants.html", {
        "event": event, "page": Paginator(enrollment, 25).get_page(request.GET.get("page")),
    })


@require_POST
@login_for_event_action
def join_event(request, event_id):
    result = services.join_event(request.user, event_id)
    if result == "joined":
        messages.success(request, "Ви записалися на подію.")
    elif result == "full":
        messages.error(request, "Місць немає.")
    elif result == "past":
        messages.error(request, "Подія вже почалася.")
    return redirect("event_detail", event_id=event_id)


@require_POST
@login_for_event_action
def cancel_registration(request, event_id):
    removed, can_open = services.cancel_registration(request.user, event_id)
    if removed:
        messages.success(request, "Ви скасували участь.")
    if can_open and request.POST.get("return_to") != "profile":
        return redirect("event_detail", event_id=event_id)
    return redirect("profile")


@require_POST
@login_for_event_action
def add_comment(request, event_id):
    event = visible_event(request.user, event_id, queryset=event_cards(Event.objects.all()))
    form = CommentForm(request.POST)
    if form.is_valid():
        services.add_comment(
            request.user, event_id, form.cleaned_data["text"], form.cleaned_data["submission_id"],
        )
        messages.success(request, "Коментар збережено.")
        return redirect("event_detail", event_id=event_id)
    return render_detail(request, event, form, status=400)


@require_safe
@login_required
def profile(request):
    created = event_cards(Event.objects.filter(author=request.user)).order_by("-starts_at", "-pk")
    enrolled = Participation.objects.filter(user=request.user, event_id=OuterRef("pk"))
    joined = event_cards(Event.objects.filter(Exists(enrolled))).annotate(
        enrolled_at=Subquery(enrolled.values("created_at")[:1]),
        can_open=Case(
            When(visibility_filter(request.user), then=Value(True)),
            default=Value(False), output_field=BooleanField(),
        ),
    ).order_by("-enrolled_at", "-pk")
    return render(request, "events/profile.html", {
        "created": Paginator(created, 12).get_page(request.GET.get("created_page")),
        "joined": Paginator(joined, 12).get_page(request.GET.get("joined_page")),
        "now": timezone.now(),
    })


@require_POST
@login_for_event_action
@sensitive_variables("token", "invite_url")
def rotate_invitation(request, event_id):
    token = services.rotate_invitation(request.user, event_id)
    path = reverse("invitation", kwargs={"token": token})
    invite_url = settings.PUBLIC_ORIGIN + path if settings.PUBLIC_ORIGIN else request.build_absolute_uri(path)
    response = render(request, "events/invite_link.html", {"event_id": event_id, "invite_url": invite_url})
    response["Referrer-Policy"] = "no-referrer"
    return response


def render_invitation(request, digest, pending=False):
    if request.method == "POST" and request.user.is_authenticated:
        event_id = services.accept_invitation(request.user, digest)
        if pending:
            request.session.pop(INVITATION_SESSION_KEY, None)
        response = redirect("event_detail", event_id=event_id)
    else:
        if not digest or not Event.objects.filter(is_private=True, invite_digest=digest).exists():
            raise Http404
        if not request.user.is_authenticated:
            request.session[INVITATION_SESSION_KEY] = digest
        response = render(request, "events/invitation.html", {
            "auth_query": urlencode({"next": reverse("invite_continue")}),
        })
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_http_methods(["GET", "POST"])
@sensitive_variables("token")
def invitation(request, token):
    return render_invitation(request, services.invitation_digest(token))


@require_http_methods(["GET", "POST"])
@login_required
def continue_invitation(request):
    return render_invitation(request, request.session.get(INVITATION_SESSION_KEY), pending=True)
