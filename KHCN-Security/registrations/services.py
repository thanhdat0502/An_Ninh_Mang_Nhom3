"""State transitions lock Topic before Registration, in one consistent order."""

from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from topics.models import Topic
from topics.permissions import visible_topics

from .models import Registration
from .permissions import visible_registrations
from .roles import can_register, can_review


class RegistrationConflict(APIException):
    status_code = 409

    def __init__(self, message, code):
        super().__init__({"detail": message, "code": code})


def register_for_topic(*, student, topic_id):
    if not can_register(student):
        raise PermissionDenied("Chỉ sinh viên có quyền đăng ký mới được gửi yêu cầu.")
    try:
        with transaction.atomic():
            topic = get_object_or_404(
                visible_topics(student).select_for_update(of=("self",)), pk=topic_id
            )
            if topic.status != Topic.Status.OPEN:
                raise RegistrationConflict(
                    "Đề tài không còn mở đăng ký.", "topic_not_open"
                )
            if Registration.objects.filter(student=student, topic=topic).exists():
                raise RegistrationConflict(
                    "Bạn đã đăng ký đề tài này.", "duplicate_registration"
                )
            registration = Registration(student=student, topic=topic)
            registration.full_clean()
            registration.save()
        return registration
    except ModelValidationError as exc:
        raise ValidationError(
            {"detail": "Thông tin đăng ký không còn hợp lệ. Vui lòng tải lại."}
        ) from exc
    except IntegrityError as exc:
        raise RegistrationConflict(
            "Đăng ký bị trùng hoặc dữ liệu liên quan vừa thay đổi.",
            "registration_conflict",
        ) from exc


def review_registration(*, reviewer, registration_id, decision):
    if not can_review(reviewer):
        raise PermissionDenied("Bạn không có quyền xét duyệt đăng ký.")
    if decision not in (Registration.Status.APPROVED, Registration.Status.REJECTED):
        raise ValidationError({"detail": "Quyết định xét duyệt không hợp lệ."})
    try:
        with transaction.atomic():
            initial = get_object_or_404(
                visible_registrations(reviewer), pk=registration_id
            )
            # Topic lock also serializes a concurrent reassignment/closure by
            # Admin. Re-evaluate the scope after acquiring this lock.
            topic = get_object_or_404(
                Topic.objects.select_for_update(), pk=initial.topic_id
            )
            registration = get_object_or_404(
                visible_registrations(reviewer).select_for_update(of=("self",)),
                pk=registration_id,
                topic=topic,
            )
            if registration.status != Registration.Status.PENDING:
                raise RegistrationConflict(
                    "Đăng ký đã được xử lý hoặc không còn chờ duyệt.",
                    "already_processed",
                )
            registration.status = decision
            registration.reviewed_by = reviewer
            registration.reviewed_at = timezone.now()
            # Only controlled transition/audit fields are written. Historical
            # registrations remain reviewable if the student's group changed.
            registration.save(
                update_fields=("status", "reviewed_by", "reviewed_at", "updated_at")
            )
        return registration
    except IntegrityError as exc:
        raise RegistrationConflict(
            "Dữ liệu xét duyệt vừa thay đổi. Vui lòng tải lại.", "review_conflict"
        ) from exc
