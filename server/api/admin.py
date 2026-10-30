from django.contrib import admin

from server.api.models import HyperliquidBackfillJob, ScoredFillDecision, ScoredFillRefreshRun


@admin.register(ScoredFillDecision)
class ScoredFillDecisionAdmin(admin.ModelAdmin):
    list_display = ("decision_id", "coin", "timestamp", "action", "severity", "calibrated_score")
    list_filter = ("coin", "action", "severity")
    search_fields = ("decision_id",)


@admin.register(ScoredFillRefreshRun)
class ScoredFillRefreshRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "status", "trigger", "refreshed_count", "duration_ms")
    list_filter = ("status", "trigger")


@admin.register(HyperliquidBackfillJob)
class HyperliquidBackfillJobAdmin(admin.ModelAdmin):
    list_display = ("job_id", "coin", "date", "status", "fills", "gold_rows", "duration_ms")
    list_filter = ("status", "coin")
