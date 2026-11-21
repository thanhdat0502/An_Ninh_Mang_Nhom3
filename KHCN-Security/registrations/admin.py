from django.contrib import admin

from accounts.models import Role
from topics.roles import business_role

from .models import Registration
from .permissions import visible_registrations


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "topic",
        "status",
        "reviewed_by",
        "reviewed_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("student__email", "topic__code", "topic__title")
    list_select_related = ("student", "topic", "reviewed_by")
    readonly_fields = (
        "student",
        "topic",
        "status",
        "reviewed_by",
        "reviewed_at",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request):
        return visible_registrations(request.user)

    def has_view_permission(self, request, obj=None):
        return business_role(
            request.user
        ) == Role.ADMIN and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Decisions must use the audited, atomic workflow instead of a dropdown.
        return False

    def has_delete_permission(self, request, obj=None):
        return False
