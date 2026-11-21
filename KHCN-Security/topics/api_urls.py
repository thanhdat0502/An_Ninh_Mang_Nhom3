from rest_framework.routers import SimpleRouter

from .api_views import TopicViewSet

app_name = "topic_api"
router = SimpleRouter()
router.register("", TopicViewSet, basename="topic")
urlpatterns = router.urls
