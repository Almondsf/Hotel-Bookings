from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    name = 'authentication'

    def ready(self):
        from hotel import checks  # noqa: F401  (registers the deployment checks)
