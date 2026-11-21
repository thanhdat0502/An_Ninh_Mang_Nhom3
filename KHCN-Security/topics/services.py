from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import APIException, ValidationError


class TopicConflict(APIException):
    status_code = 409
    default_detail = "Dữ liệu liên quan đã thay đổi. Vui lòng tải lại và thử lại."


def persist_topic(topic):
    try:
        with transaction.atomic():
            topic.full_clean()
            topic.save()
        return topic
    except ModelValidationError as exc:
        errors = getattr(exc, "message_dict", None)
        if errors:
            errors = {
                "non_field_errors" if key == "__all__" else key: value
                for key, value in errors.items()
            }
        raise ValidationError(
            errors or {"detail": "Thông tin đề tài không hợp lệ."}
        ) from exc
    except IntegrityError as exc:
        if getattr(exc.__cause__, "sqlstate", None) == "23505":
            raise ValidationError({"code": ["Mã đề tài đã tồn tại."]}) from exc
        raise TopicConflict() from exc


def delete_topic(topic):
    try:
        with transaction.atomic():
            topic.delete()
    except (ProtectedError, IntegrityError) as exc:
        # Never serialize related registration/student records in an error.
        raise TopicConflict("Đề tài có dữ liệu liên quan, không thể xóa.") from exc
