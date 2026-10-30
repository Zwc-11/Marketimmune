from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "server.api"
    label = "api"
    verbose_name = "MarketImmune API"
