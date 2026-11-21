from rest_framework.routers import SimpleRouter

from .management_api import AccountViewSet

app_name = "account_management_api"
router = SimpleRouter()
router.register("", AccountViewSet, basename="account")
urlpatterns = router.urls
