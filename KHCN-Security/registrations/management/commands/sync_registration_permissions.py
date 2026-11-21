from django.core.management.base import BaseCommand

from registrations.roles import sync_registration_permissions


class Command(BaseCommand):
    help = "Cấp quyền đăng ký/xét duyệt tối thiểu cho Groups hiện có; không đổi user hoặc dữ liệu."

    def handle(self, *args, **options):
        sync_registration_permissions()
        self.stdout.write(
            self.style.SUCCESS("Đã đồng bộ permissions đăng ký/xét duyệt.")
        )
