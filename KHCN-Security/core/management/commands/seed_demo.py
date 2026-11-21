import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Role
from core.demo_data import DEMO_ACCOUNTS, DEMO_TOPICS
from registrations.roles import sync_registration_permissions
from topics.models import Topic
from topics.roles import sync_topic_permissions


class Command(BaseCommand):
    help = "Tạo nhóm quyền, ba tài khoản demo và 12 đề tài; không đổi mật khẩu hay ghi đè đề tài đã có."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        passwords = {}
        # Validate every secret before writing anything. Never print submitted values.
        for email, full_name, role, variable in DEMO_ACCOUNTS:
            password = os.getenv(variable, "")
            if not password:
                raise CommandError(f"Thiếu {variable}; hãy tự nhập vào .env.")
            try:
                validate_password(password, User(email=email, full_name=full_name))
            except ValidationError:
                raise CommandError(
                    f"{variable} không đạt chính sách mật khẩu Django (tối thiểu 12 ký tự)."
                ) from None
            passwords[role] = password
        if len(set(passwords.values())) != len(DEMO_ACCOUNTS):
            raise CommandError("Ba tài khoản demo phải sử dụng ba mật khẩu khác nhau.")

        groups = {
            role: Group.objects.get_or_create(name=role)[0] for role in Role.values
        }
        # Preserve existing Admin management permissions and add topic read roles.
        permissions = Permission.objects.filter(
            content_type__app_label__in=["accounts", "topics", "registrations"]
        )
        groups[Role.ADMIN].permissions.add(*permissions)
        groups[Role.ADMIN].permissions.add(
            *Permission.objects.filter(
                content_type__app_label="auth", codename="view_group"
            )
        )
        sync_topic_permissions()
        sync_registration_permissions()
        users = {}
        created_users = 0
        for email, full_name, role, variable in DEMO_ACCOUNTS:
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                user = User.objects.create_user(
                    email=email,
                    full_name=full_name,
                    password=passwords[role],
                    is_staff=role == Role.ADMIN,
                )
                created_users += 1
            elif not user.groups.filter(name=role).exists():
                # Refuse to silently elevate an unrelated pre-existing account.
                raise CommandError(
                    f"Tài khoản demo {email} đã tồn tại ngoài nhóm {role}; cần kiểm tra thủ công."
                )
            user.groups.add(groups[role])
            users[role] = user

        created_topics = 0
        for code, title, description in DEMO_TOPICS:
            if not Topic.objects.filter(code=code).exists():
                topic = Topic(
                    code=code,
                    title=title,
                    description=description,
                    lecturer=users[Role.LECTURER],
                    status=Topic.Status.OPEN,
                )
                topic.full_clean()
                topic.save()
                created_topics += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Seed hoàn tất: thêm {created_users} tài khoản, {created_topics} đề tài. "
                "Dữ liệu và mật khẩu đã có được giữ nguyên."
            )
        )
