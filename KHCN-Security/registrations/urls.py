from django.urls import path

from .views import registration_workspace

app_name = "registrations"
urlpatterns = [path("dang-ky/", registration_workspace, name="list")]
