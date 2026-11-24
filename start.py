"""Start Tusovka in an isolated HTTP evaluation environment."""
import os


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ["TUSOVKA_EVALUATION"] = "1"
    os.environ["TUSOVKA_DEBUG"] = "0"

    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.management import call_command
    from waitress import serve

    from config.wsgi import application

    port = int(os.environ.get("PORT", "8000"))
    call_command("migrate", interactive=False, verbosity=1)
    print(f"Tusovka listening on 0.0.0.0:{port} (GET /healthz/)", flush=True)
    serve(
        StaticFilesHandler(application),
        host="0.0.0.0",
        port=port,
        max_request_body_size=4 * 1024 * 1024,
        max_request_header_size=32 * 1024,
        channel_timeout=30,
    )


if __name__ == "__main__":
    main()
