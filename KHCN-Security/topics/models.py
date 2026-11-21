from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from accounts.models import Role


class Topic(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Bản nháp"
        OPEN = "OPEN", "Đang mở"
        CLOSED = "CLOSED", "Đã đóng"
        COMPLETED = "COMPLETED", "Hoàn thành"

    code = models.CharField(
        "Mã đề tài",
        max_length=30,
        unique=True,
        validators=[
            RegexValidator(
                r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$", "Mã gồm chữ in hoa, số và dấu gạch nối."
            )
        ],
    )
    title = models.CharField("Tên đề tài", max_length=255)
    description = models.TextField("Mô tả")
    lecturer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="supervised_topics",
        verbose_name="Giảng viên phụ trách",
        limit_choices_to={"groups__name": Role.LECTURER},
    )
    status = models.CharField(
        "Trạng thái", max_length=12, choices=Status.choices, default=Status.DRAFT
    )
    created_at = models.DateTimeField("Ngày tạo", auto_now_add=True)
    updated_at = models.DateTimeField("Ngày cập nhật", auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Đề tài"
        verbose_name_plural = "Đề tài"
        indexes = [
            models.Index(fields=["status", "code"], name="topic_status_code_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["DRAFT", "OPEN", "CLOSED", "COMPLETED"]),
                name="topic_valid_status",
            ),
            models.CheckConstraint(
                condition=~models.Q(code=""), name="topic_code_not_empty"
            ),
            models.CheckConstraint(
                condition=~models.Q(title=""), name="topic_title_not_empty"
            ),
            models.CheckConstraint(
                condition=~models.Q(description=""), name="topic_description_not_empty"
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.lecturer_id
            and not self.lecturer.groups.filter(name=Role.LECTURER).exists()
        ):
            raise ValidationError(
                {"lecturer": "Tài khoản phụ trách phải thuộc nhóm LECTURER."}
            )

    def __str__(self):
        return f"{self.code} — {self.title}"
