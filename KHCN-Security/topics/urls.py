from django.urls import path

from . import views

app_name = "topics"
urlpatterns = [
    path("de-tai/", views.topic_workspace, name="list"),
    path("de-tai/<int:pk>/", views.topic_detail, name="detail"),
]
