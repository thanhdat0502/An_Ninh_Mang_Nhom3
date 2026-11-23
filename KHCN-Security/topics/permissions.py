from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import Role

from .models import Topic
from .roles import business_role, can_manage_topic


def visible_topics(user):
    queryset = Topic.objects.select_related("lecturer").order_by("code")
    role = business_role(user)
    if role == Role.ADMIN:
        return queryset
    if role == Role.LECTURER:
        return queryset.filter(lecturer=user)
    if role == Role.STUDENT:
        return queryset.exclude(status=Topic.Status.DRAFT)
    return queryset.none()


class TopicAccess(BasePermission):
    message = "Bạn không có quyền thực hiện thao tác với đề tài này."
    write_permissions = {
        "POST": "add",
        "PUT": "change",
        "PATCH": "change",
        "DELETE": "delete",
    }

    def has_permission(self, request, view):
        user = request.user
        if not business_role(user):
            return False
        if view.action == "lecturers":
            return business_role(user) == Role.ADMIN and (
                can_manage_topic(user, "add") or can_manage_topic(user, "change")
            )
        if request.method in SAFE_METHODS:
            return user.has_perm("topics.view_topic")
        permission = self.write_permissions.get(request.method)
        return bool(permission and can_manage_topic(user, permission))

    def has_object_permission(self, request, view, obj):
        if request.method not in SAFE_METHODS:
            return can_manage_topic(
                request.user, self.write_permissions[request.method]
            )
        role = business_role(request.user)
        return (
            role == Role.ADMIN
            or (role == Role.LECTURER and obj.lecturer_id == request.user.pk)
            or (role == Role.STUDENT and obj.status != Topic.Status.DRAFT)
        )
