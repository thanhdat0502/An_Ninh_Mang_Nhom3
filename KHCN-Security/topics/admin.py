from django.contrib import admin

from accounts.models import Role

from .models import Topic
from .roles import business_role


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "lecturer", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("code", "title", "lecturer__email", "lecturer__full_name")
    list_select_related = ("lecturer",)
    readonly_fields = ("created_at", "updated_at")

    @staticmethod
    def can_administer_topics(request):
        return request.user.is_superuser or business_role(request.user) == Role.ADMIN

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset if self.can_administer_topics(request) else queryset.none()

    def has_module_permission(self, request):
        return self.can_administer_topics(request) and super().has_module_permission(
            request
        )

    def has_view_permission(self, request, obj=None):
        return self.can_administer_topics(request) and super().has_view_permission(
            request, obj
        )

    def has_add_permission(self, request):
        return self.can_administer_topics(request) and super().has_add_permission(
            request
        )

    def has_change_permission(self, request, obj=None):
        return self.can_administer_topics(request) and super().has_change_permission(
            request, obj
        )

    def has_delete_permission(self, request, obj=None):
        return self.can_administer_topics(request) and super().has_delete_permission(
            request, obj
        )
