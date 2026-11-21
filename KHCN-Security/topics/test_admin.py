import secrets

from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings

from accounts.models import Role, User

from .models import Topic


@override_settings(SECURE_SSL_REDIRECT=False)
class TopicAdminSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        password = secrets.token_urlsafe(24)
        cls.users = {}
        for role in Role.values:
            group = Group.objects.create(name=role)
            group.permissions.add(
                *Permission.objects.filter(content_type__app_label="topics")
            )
            user = User.objects.create_user(
                f"{role.lower()}@topic-admin.example",
                password,
                full_name=role,
                is_staff=True,
            )
            user.groups.add(group)
            cls.users[role] = user
        cls.draft = Topic.objects.create(
            code="PRIVATE-DRAFT",
            title="Private draft",
            description="Private content",
            lecturer=cls.users[Role.LECTURER],
            status=Topic.Status.DRAFT,
        )
        cls.root = User.objects.create_superuser(
            "root@topic-admin.example", password, full_name="System root"
        )

    def test_staff_without_admin_role_cannot_read_or_manage_topics(self):
        for role in (Role.STUDENT, Role.LECTURER):
            self.client.force_login(self.users[role])
            for url in (
                "/admin/topics/topic/",
                "/admin/topics/topic/add/",
                f"/admin/topics/topic/{self.draft.pk}/change/",
                f"/admin/topics/topic/{self.draft.pk}/delete/",
            ):
                with self.subTest(role=role, url=url):
                    result = self.client.get(url)
                    self.assertEqual(result.status_code, 403)
                    self.assertNotContains(result, self.draft.title, status_code=403)

    def test_non_admin_cannot_edit_by_direct_post(self):
        self.client.force_login(self.users[Role.STUDENT])
        response = self.client.post(
            f"/admin/topics/topic/{self.draft.pk}/change/",
            {
                "code": self.draft.code,
                "title": "Unauthorized change",
                "description": "Changed",
                "lecturer": self.users[Role.LECTURER].pk,
                "status": "OPEN",
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.title, "Private draft")
        self.assertEqual(self.draft.status, Topic.Status.DRAFT)

    def test_admin_keeps_access_to_all_topics(self):
        self.client.force_login(self.users[Role.ADMIN])
        self.assertContains(self.client.get("/admin/topics/topic/"), self.draft.title)

    def test_native_system_superuser_keeps_topic_administration(self):
        self.client.force_login(self.root)
        self.assertContains(self.client.get("/admin/topics/topic/"), self.draft.title)
