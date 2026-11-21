from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Quản trị viên"
    LECTURER = "LECTURER", "Giảng viên"
    STUDENT = "STUDENT", "Sinh viên"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email or not email.strip():
            raise ValueError("Email không được để trống.")
        user = self.model(
            email=self.normalize_email(email.strip()).lower(), **extra_fields
        )
        user.set_password(password)
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("Superuser phải có is_staff=True và is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, email):
        return self.get(email__iexact=email.strip())


class User(AbstractUser):
    username = None
    first_name = None
    last_name = None
    email = models.EmailField("Email", unique=True)
    full_name = models.CharField("Họ và tên", max_length=150)
    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["email"]
        verbose_name = "Tài khoản"
        verbose_name_plural = "Tài khoản"
        constraints = [
            models.UniqueConstraint(
                Lower("email"), name="user_email_case_insensitive_unique"
            ),
            models.CheckConstraint(
                condition=~models.Q(email=""), name="user_email_not_empty"
            ),
            models.CheckConstraint(
                condition=~models.Q(full_name=""), name="user_full_name_not_empty"
            ),
        ]

    def clean(self):
        super().clean()
        self.email = self.email.strip().lower()
        self.full_name = self.full_name.strip()

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name

    def __str__(self):
        return f"{self.full_name} ({self.email})"
