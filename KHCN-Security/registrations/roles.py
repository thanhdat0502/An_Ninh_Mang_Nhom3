from django.contrib.auth.models import Group, Permission
from django.db import transaction

from accounts.models import Role
from topics.roles import business_role


@transaction.atomic
def sync_registration_permissions():
    minimums = {
        Role.ADMIN: ("view_registration", "change_registration"),
        Role.LECTURER: ("view_registration", "change_registration"),
        Role.STUDENT: ("view_registration", "add_registration"),
    }
    for role, codenames in minimums.items():
        group, _ = Group.objects.get_or_create(name=role)
        permissions = Permission.objects.filter(
            content_type__app_label="registrations",
            content_type__model="registration",
            codename__in=codenames,
        )
        group.permissions.add(*permissions)


def can_register(user):
    return business_role(user) == Role.STUDENT and user.has_perms(
        ("registrations.add_registration", "topics.view_topic")
    )


def can_review(user):
    return business_role(user) in (Role.ADMIN, Role.LECTURER) and user.has_perm(
        "registrations.change_registration"
    )
