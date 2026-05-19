from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'
    verbose_name = 'Dashboard'
    
    def ready(self):
        """Initialize app when Django starts"""
        # Import signals here if needed
        pass
