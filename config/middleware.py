import sqlite3

from django.db import OperationalError
from django.shortcuts import render
from django.utils.cache import add_never_cache_headers
from django.utils.deprecation import MiddlewareMixin


class DynamicResponsesMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        add_never_cache_headers(response)
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, OperationalError):
            code = getattr(exception.__cause__, "sqlite_errorcode", 0)
            if (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                response = render(request, "busy.html", status=503)
                response["Retry-After"] = "2"
                return response
        return None
