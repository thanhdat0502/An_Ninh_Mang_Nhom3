from django.urls import path

from .views import login_page, workspace

app_name = "accounts"
urlpatterns = [
    path("dang-nhap/", login_page, name="login"),
    path("tai-khoan/", workspace, name="workspace"),
]
