from rest_framework.routers import SimpleRouter

from .api_views import RegistrationViewSet

app_name = "registration_api"
router = SimpleRouter()
router.register("", RegistrationViewSet, basename="registration")
urlpatterns = router.urls
