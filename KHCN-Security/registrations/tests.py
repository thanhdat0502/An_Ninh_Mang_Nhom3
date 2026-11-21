from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from accounts.models import Role
from topics.models import Topic

from .models import Registration


class RegistrationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.lecturer = User.objects.create_user(
            "lecturer@example.com", full_name="Giảng viên"
        )
        cls.student = User.objects.create_user(
            "student@example.com", full_name="Sinh viên"
        )
        cls.lecturer.groups.add(Group.objects.create(name=Role.LECTURER))
        cls.student.groups.add(Group.objects.create(name=Role.STUDENT))
        cls.topic = Topic.objects.create(
            code="TEST-001",
            title="Đề tài",
            description="Mô tả",
            lecturer=cls.lecturer,
            status=Topic.Status.OPEN,
        )

    def test_valid_registration(self):
        registration = Registration(student=self.student, topic=self.topic)
        registration.full_clean()
        registration.save()
        self.assertEqual(registration.status, Registration.Status.PENDING)
        self.assertIsNotNone(registration.created_at)

    def test_duplicate_pair_rejected_at_database(self):
        Registration.objects.create(student=self.student, topic=self.topic)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Registration.objects.create(student=self.student, topic=self.topic)

    def test_invalid_status_rejected_at_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Registration.objects.create(
                student=self.student, topic=self.topic, status="INVALID"
            )

    def test_non_student_rejected_by_validation(self):
        with self.assertRaises(ValidationError):
            Registration(student=self.lecturer, topic=self.topic).full_clean()

    def test_closed_topic_rejected_for_new_registration(self):
        self.topic.status = Topic.Status.CLOSED
        self.topic.save()
        with self.assertRaises(ValidationError):
            Registration(student=self.student, topic=self.topic).full_clean()

    def test_registered_topic_and_student_are_protected(self):
        Registration.objects.create(student=self.student, topic=self.topic)
        with self.assertRaises(ProtectedError):
            self.topic.delete()
        with self.assertRaises(ProtectedError):
            self.student.delete()
