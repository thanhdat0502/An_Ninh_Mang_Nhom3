"""The secondary Django Admin must not bypass the business role boundary."""

import secrets

from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings

from .models import Role, User


@override_settings(SECURE_SSL_REDIRECT=False)
class AccountAdminSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.groups = {role: Group.objects.create(name=role) for role in Role.values}
        permissions = Permission.objects.filter(content_type__app_label="accounts")
        for group in cls.groups.values():
            group.permissions.add(*permissions)
        cls.users = {}
        for role in Role.values:
            user = User.objects.create_user(
                f"{role.lower()}@admin-test.example",
                cls.password,
                full_name=role,
                is_staff=True,
            )
            user.groups.add(cls.groups[role])
            cls.users[role] = user
        cls.target = User.objects.create_user(
            "target@admin-test.example", cls.password, full_name="Target"
        )
        cls.target.groups.add(cls.groups[Role.STUDENT])
        cls.root = User.objects.create_superuser(
            "root@admin-test.example", cls.password, full_name="System administrator"
        )

    def test_staff_student_or_lecturer_cannot_manage_users_even_with_model_permissions(
        self,
    ):
        for role in (Role.STUDENT, Role.LECTURER):
            self.client.force_login(self.users[role])
            for path in (
                "/admin/accounts/user/",
                "/admin/accounts/user/add/",
                f"/admin/accounts/user/{self.target.pk}/change/",
                f"/admin/accounts/user/{self.target.pk}/delete/",
                f"/admin/accounts/user/{self.target.pk}/password/",
            ):
                with self.subTest(role=role, path=path):
                    self.assertEqual(self.client.get(path).status_code, 403)

    def test_student_cannot_promote_self_by_crafted_admin_post(self):
        actor = self.users[Role.STUDENT]
        self.client.force_login(actor)
        result = self.client.post(
            f"/admin/accounts/user/{actor.pk}/change/",
            {
                "email": actor.email,
                "full_name": actor.full_name,
                "is_active": "on",
                "groups": [self.groups[Role.ADMIN].pk],
                "_save": "Save",
            },
        )
        self.assertEqual(result.status_code, 403)
        self.assertFalse(actor.groups.filter(name=Role.ADMIN).exists())

    def test_admin_can_assign_existing_business_group(self):
        self.client.force_login(self.users[Role.ADMIN])
        result = self.client.post(
            f"/admin/accounts/user/{self.target.pk}/change/",
            {
                "email": self.target.email,
                "full_name": self.target.full_name,
                "is_active": "on",
                "groups": [self.groups[Role.LECTURER].pk],
                "_save": "Save",
            },
        )
        self.assertEqual(result.status_code, 302)
        self.assertEqual(
            list(self.target.groups.values_list("name", flat=True)), [Role.LECTURER]
        )
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_staff)
        self.assertFalse(self.target.is_superuser)

    def test_admin_cannot_remove_own_role_or_deactivate_self_via_admin_form(self):
        actor = self.users[Role.ADMIN]
        self.client.force_login(actor)
        result = self.client.post(
            f"/admin/accounts/user/{actor.pk}/change/",
            {
                "email": actor.email,
                "full_name": actor.full_name,
                "groups": [self.groups[Role.STUDENT].pk],
                "_save": "Save",
            },
        )
        self.assertEqual(result.status_code, 302)
        actor.refresh_from_db()
        self.assertTrue(actor.is_active)
        self.assertTrue(actor.groups.filter(name=Role.ADMIN).exists())

    def test_native_system_superuser_keeps_account_administration(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.get("/admin/accounts/user/").status_code, 200)

    def test_regular_admin_cannot_change_system_privileges(self):
        self.client.force_login(self.users[Role.ADMIN])
        result = self.client.post(
            f"/admin/accounts/user/{self.target.pk}/change/",
            {
                "email": self.target.email,
                "full_name": self.target.full_name,
                "is_active": "on",
                "is_staff": "on",
                "is_superuser": "on",
                "groups": [self.groups[Role.STUDENT].pk],
                "_save": "Save",
            },
        )
        self.assertEqual(result.status_code, 302)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_staff)
        self.assertFalse(self.target.is_superuser)
