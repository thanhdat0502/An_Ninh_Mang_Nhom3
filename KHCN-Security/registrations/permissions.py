from rest_framework.permissions import BasePermission

from accounts.models import Role
from topics.roles import business_role

from .models import Registration
from .roles import can_register, can_review


def visible_registrations(user):
    queryset = Registration.objects.select_related(
        "student", "topic__lecturer", "reviewed_by"
    ).order_by("-created_at", "-pk")
    role = business_role(user)
    if role == Role.ADMIN:
        return queryset
    if role == Role.LECTURER:
        return queryset.filter(topic__lecturer=user)
    if role == Role.STUDENT:
        return queryset.filter(student=user)
    return queryset.none()


class RegistrationAccess(BasePermission):
    message = "Bạn không có quyền thực hiện thao tác với đăng ký này."

    def has_permission(self, request, view):
        if not business_role(request.user):
            return False
        if view.action == "create":
            return can_register(request.user)
        if view.action in ("approve", "reject"):
            return can_review(request.user)
        # Unsupported methods will reach DRF's 405 handler, never a generic
        # state/identity update operation.
        return request.user.has_perm("registrations.view_registration")

    def has_object_permission(self, request, view, obj):
        role = business_role(request.user)
        return (
            role == Role.ADMIN
            or (role == Role.LECTURER and obj.topic.lecturer_id == request.user.pk)
            or (role == Role.STUDENT and obj.student_id == request.user.pk)
        )
