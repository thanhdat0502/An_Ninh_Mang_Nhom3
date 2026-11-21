from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import User


def update_account(*, actor, account_id, changes):
    """Edit profile/status only; keep groups, password and privilege flags intact."""
    try:
        with transaction.atomic():
            user = get_object_or_404(User.objects.select_for_update(), pk=account_id)
            if user.is_superuser and not actor.is_superuser:
                raise PermissionDenied("Không được sửa tài khoản quản trị cấp cao.")
            if user.pk == actor.pk and changes.get("is_active") is False:
                raise ValidationError(
                    {"is_active": ["Không thể tự khóa tài khoản đang sử dụng."]}
                )
            for field, value in changes.items():
                setattr(user, field, value)
            try:
                user.full_clean()
            except ModelValidationError as error:
                # Never return model exception details or existing account values.
                fields = getattr(error, "message_dict", {})
                if "email" in fields or "__all__" in fields:
                    raise ValidationError(
                        {"email": ["Email không hợp lệ hoặc đã được sử dụng."]}
                    ) from None
                raise ValidationError("Thông tin tài khoản chưa hợp lệ.") from None
            user.save(update_fields=list(changes))
            return user
    except IntegrityError:
        raise ValidationError(
            {"email": ["Email không hợp lệ hoặc đã được sử dụng."]}
        ) from None
