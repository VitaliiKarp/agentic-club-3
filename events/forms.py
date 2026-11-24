from io import BytesIO
from uuid import uuid4

from django import forms
from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import Event

MAX_COVER_BYTES = 3 * 1024 * 1024
MAX_COVER_PIXELS = 12_000_000


def prepare_cover(upload):
    if upload.size > MAX_COVER_BYTES:
        raise ValidationError("Обкладинка має важити до 3 МБ.")
    try:
        with Image.open(upload, formats=("JPEG", "PNG", "WEBP")) as source:
            if source.width * source.height > MAX_COVER_PIXELS:
                raise ValidationError("Роздільна здатність має бути до 12 мегапікселів.")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail((1600, 1600))
            canvas = Image.new("RGB", image.size, "white")
            canvas.paste(image, mask=image.getchannel("A"))
            output = BytesIO()
            canvas.save(output, "JPEG", quality=85, optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise ValidationError("Завантажте коректне зображення JPEG, PNG або WebP.") from error


class EventForm(forms.ModelForm):
    submission_id = forms.UUIDField(required=False, widget=forms.HiddenInput, initial=uuid4)
    starts_at = forms.DateTimeField(
        label="Дата й час початку (Київ)",
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M:%S", attrs={"type": "datetime-local", "step": "1"},
        ),
    )
    capacity = forms.IntegerField(label="Кількість місць", min_value=1, max_value=1000)
    is_private = forms.TypedChoiceField(
        label="Видимість",
        choices=(("0", "Публічна"), ("1", "Приватна")),
        coerce=lambda value: str(value) in {"1", "True"},
    )
    cover_file = forms.FileField(
        label="Обкладинка",
        required=False,
        help_text="JPEG, PNG або WebP до 3 МБ. Якщо не вибрати файл, буде стандартна обкладинка.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )

    class Meta:
        model = Event
        fields = ("title", "description", "starts_at", "capacity", "is_private")
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["is_private"] = "1" if self.instance.is_private else "0"
        if self.instance.pk:
            self.fields.pop("submission_id")
            self.fields["cover_file"].help_text = "JPEG, PNG або WebP до 3 МБ. Без нового файлу поточна обкладинка збережеться."

    def clean_cover_file(self):
        upload = self.cleaned_data["cover_file"]
        return prepare_cover(upload) if upload else None


class CommentForm(forms.Form):
    submission_id = forms.UUIDField(required=False, widget=forms.HiddenInput, initial=uuid4)
    text = forms.CharField(
        label="Коментар", max_length=1000, widget=forms.Textarea(attrs={"rows": 3}),
    )
