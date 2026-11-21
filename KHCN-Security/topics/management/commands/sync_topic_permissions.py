from django.core.management.base import BaseCommand

from topics.roles import sync_topic_permissions


class Command(BaseCommand):
    help = "Bổ sung quyền đề tài tối thiểu cho ba Groups; không đổi user, password hoặc dữ liệu."

    def handle(self, *args, **options):
        sync_topic_permissions()
        self.stdout.write(
            self.style.SUCCESS("Đã đồng bộ permissions đề tài cho ba Groups.")
        )
