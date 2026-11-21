from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import Role


class Registration(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Chờ duyệt"
        APPROVED = "APPROVED", "Đã duyệt"
        REJECTED = "REJECTED", "Từ chối"
        WITHDRAWN = "WITHDRAWN", "Đã rút"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registrations",
        verbose_name="Sinh viên",
        limit_choices_to={"groups__name": Role.STUDENT},
    )
    topic = models.ForeignKey(
        "topics.Topic",
        on_delete=models.PROTECT,
        related_name="registrations",
        verbose_name="Đề tài",
    )
    status = models.CharField(
        "Trạng thái", max_length=12, choices=Status.choices, default=Status.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_registrations",
        verbose_name="Người xét duyệt",
    )
    reviewed_at = models.DateTimeField("Thời điểm xét duyệt", null=True, blank=True)
    created_at = models.DateTimeField("Ngày đăng ký", auto_now_add=True)
    updated_at = models.DateTimeField("Ngày cập nhật", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Đăng ký đề tài"
        verbose_name_plural = "Đăng ký đề tài"
        indexes = [
            models.Index(
                fields=["topic", "status"], name="registration_topic_status_idx"
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "topic"], name="unique_student_topic"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["PENDING", "APPROVED", "REJECTED", "WITHDRAWN"]
                ),
                name="registration_valid_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(reviewed_by__isnull=True, reviewed_at__isnull=True)
                    | models.Q(
                        reviewed_by__isnull=False,
                        reviewed_at__isnull=False,
                        status__in=["APPROVED", "REJECTED"],
                    )
                ),
                name="registration_review_audit_consistent",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.student_id
            and not self.student.groups.filter(name=Role.STUDENT).exists()
        ):
            raise ValidationError({"student": "Người đăng ký phải thuộc nhóm STUDENT."})
        if (
            self._state.adding
            and self.topic_id
            and self.topic.status != self.topic.Status.OPEN
        ):
            raise ValidationError({"topic": "Chỉ được đăng ký đề tài đang mở."})

    def __str__(self):
        return f"{self.student.email} — {self.topic.code}"
