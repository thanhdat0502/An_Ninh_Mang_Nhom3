from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication

from .security import enforce_csrf, enforce_transport


class CookieJWTAuthentication(JWTAuthentication):
    """Only JWT access cookies authenticate API requests; sessions are ignored."""

    def authenticate(self, request):
        enforce_transport(request)
        raw_token = request.COOKIES.get(settings.JWT_ACCESS_COOKIE)
        if not raw_token:
            return None
        token = self.get_validated_token(raw_token)
        user = self.get_user(token)
        enforce_csrf(request)
        return user, token

    def authenticate_header(self, request):
        return 'JWT realm="api"'
