"""Extend the existing Django Groups; no parallel role store or role claims."""

from django.contrib.auth.models import Group, Permission
from django.db import transaction

from accounts.models import Role


@transaction.atomic
def sync_topic_permissions():
    for role in Role.values:
        group, _ = Group.objects.get_or_create(name=role)
        permissions = Permission.objects.filter(
            content_type__app_label="topics",
            content_type__model="topic",
        )
        if role != Role.ADMIN:
            permissions = permissions.filter(codename="view_topic")
        group.permissions.add(*permissions)


def business_role(user):
    if not user.is_authenticated or not user.is_active:
        return None
    groups = set(user.groups.values_list("name", flat=True))
    # Explicit precedence for users with several groups; a student membership
    # cannot widen a lecturer's scope. Staff/superuser flags do not choose roles.
    return next((role for role in Role.values if role in groups), None)


def can_manage_topic(user, permission):
    return business_role(user) == Role.ADMIN and user.has_perm(
        f"topics.{permission}_topic"
    )
