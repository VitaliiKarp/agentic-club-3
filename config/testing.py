from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import connections
from django.test.runner import DiscoverRunner


class FileSQLiteRunner(DiscoverRunner):
    def run_tests(self, test_labels, **kwargs):
        configuration = connections["default"].settings_dict["TEST"]
        original_name = configuration.get("NAME")
        with TemporaryDirectory(prefix="tusovka-test-") as directory:
            configuration["NAME"] = str(Path(directory) / "test.sqlite3")
            try:
                return super().run_tests(test_labels, **kwargs)
            finally:
                configuration["NAME"] = original_name
