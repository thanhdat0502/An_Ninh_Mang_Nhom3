from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from topics.roles import business_role

from .forms import AccountChangeForm, AccountCreationForm
from .models import Role, User


@admin.register(User)
class AccountAdmin(UserAdmin):
    form = AccountChangeForm
    add_form = AccountCreationForm
    ordering = ("email",)
    list_display = ("email", "full_name", "is_active", "is_staff")
    search_fields = ("email", "full_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Thông tin cá nhân", {"fields": ("full_name",)}),
        (
            "Quyền truy cập",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Thời gian", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "password1", "password2"),
            },
        ),
    )
    readonly_fields = ("last_login", "date_joined")

    @staticmethod
    def can_administer_accounts(request):
        # Keep native system-superuser administration. A business staff account
        # must also be ADMIN; accidentally granted model permissions are not enough.
        return request.user.is_superuser or business_role(request.user) == Role.ADMIN

    def has_module_permission(self, request):
        return self.can_administer_accounts(request) and super().has_module_permission(
            request
        )

    def has_view_permission(self, request, obj=None):
        return self.can_administer_accounts(request) and super().has_view_permission(
            request, obj
        )

    def has_add_permission(self, request):
        return self.can_administer_accounts(request) and super().has_add_permission(
            request
        )

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            fields = (*fields, "is_staff", "is_superuser", "user_permissions")
            if obj and obj.pk == request.user.pk:
                fields = (*fields, "groups", "is_active")
        return fields

    def has_change_permission(self, request, obj=None):
        if not self.can_administer_accounts(request):
            return False
        if obj and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if not self.can_administer_accounts(request):
            return False
        if (
            obj
            and (obj.is_superuser or obj.pk == request.user.pk)
            and not request.user.is_superuser
        ):
            return False
        return super().has_delete_permission(request, obj)
