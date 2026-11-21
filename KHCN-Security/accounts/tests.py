import secrets

from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

User = get_user_model()


class UserModelTests(TestCase):
    def test_email_login_and_password_hashing(self):
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(
            "  Student@Example.COM ", password, full_name="Sinh viên"
        )
        self.assertEqual(user.email, "student@example.com")
        self.assertNotEqual(user.password, password)
        self.assertTrue(user.check_password(password))
        self.assertEqual(
            authenticate(email="STUDENT@EXAMPLE.COM", password=password), user
        )
        user.is_active = False
        user.save()
        self.assertIsNone(authenticate(email=user.email, password=password))

    def test_database_rejects_case_insensitive_duplicate_email(self):
        User.objects.create_user("student@example.com", full_name="Sinh viên")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create(email="STUDENT@example.com", full_name="Tài khoản khác")

    def test_missing_email_and_full_name_are_rejected(self):
        with self.assertRaises(ValueError):
            User.objects.create_user("", full_name="Sinh viên")
        with self.assertRaises(ValidationError):
            User.objects.create_user("student@example.com", full_name="   ")

    def test_superuser_flags(self):
        user = User.objects.create_superuser(
            "owner@example.com", full_name="Chủ hệ thống"
        )
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                "other@example.com", full_name="Khác", is_staff=False
            )
