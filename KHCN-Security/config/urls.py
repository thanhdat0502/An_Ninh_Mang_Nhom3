from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Quản trị KHCN sinh viên"
admin.site.site_title = "KHCN sinh viên"
admin.site.index_title = "Quản lý dữ liệu"
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.api_urls")),
    path("api/accounts/", include("accounts.management_urls")),
    path("api/topics/", include("topics.api_urls")),
    path("api/registrations/", include("registrations.api_urls")),
    path("", include("registrations.urls")),
    path("", include("topics.urls")),
    path("", include("accounts.urls")),
    path("", include("core.urls")),
]
