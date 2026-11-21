from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from accounts.models import Role

from .models import Topic


class TopicModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lecturer = get_user_model().objects.create_user(
            "lecturer@example.com", full_name="Giảng viên"
        )
        cls.lecturer.groups.add(Group.objects.create(name=Role.LECTURER))
        cls.topic = Topic.objects.create(
            code="TEST-001",
            title="An toàn mạng",
            description="Nội dung nghiên cứu",
            lecturer=cls.lecturer,
            status=Topic.Status.OPEN,
        )

    def test_valid_topic_and_timestamps(self):
        self.topic.full_clean()
        self.assertIsNotNone(self.topic.created_at)
        self.assertIn("TEST-001", str(self.topic))

    def test_unique_code_and_status_are_database_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Topic.objects.create(
                code=self.topic.code,
                title="Trùng",
                description="Mô tả",
                lecturer=self.lecturer,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Topic.objects.filter(pk=self.topic.pk).update(status="INVALID")

    def test_lecturer_group_required_by_validation(self):
        self.lecturer.groups.clear()
        with self.assertRaises(ValidationError):
            self.topic.full_clean()

    def test_lecturer_is_protected_from_deletion(self):
        with self.assertRaises(ProtectedError):
            self.lecturer.delete()

    def test_invalid_code_rejected(self):
        self.topic.code = "mã không hợp lệ"
        with self.assertRaises(ValidationError):
            self.topic.full_clean()
