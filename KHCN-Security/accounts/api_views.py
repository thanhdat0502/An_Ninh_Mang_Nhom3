from django.conf import settings
from django.middleware.csrf import get_token, rotate_token
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .security import (
    RequireCSRF,
    clear_auth_cookies,
    enforce_transport,
    set_auth_cookies,
)
from .serializers import CurrentUserSerializer, LoginSerializer
from .services import issue_tokens, revoke_refresh, rotate_refresh


class AuthAPIView(APIView):
    """No session or access-token prerequisite for renewing/ending a session."""

    authentication_classes = ()
    permission_classes = (RequireCSRF,)

    def initial(self, request, *args, **kwargs):
        enforce_transport(request)
        return super().initial(request, *args, **kwargs)

    def get_authenticate_header(self, request):
        return 'JWT realm="api"'

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["Pragma"] = "no-cache"
        return response


class CSRFView(AuthAPIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class LoginView(AuthAPIView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        refresh = issue_tokens(user, request.COOKIES.get(settings.JWT_REFRESH_COOKIE))
        rotate_token(request)
        response = Response(
            {
                "user": CurrentUserSerializer(user).data,
                "csrfToken": get_token(request),
            }
        )
        return set_auth_cookies(response, request, refresh)


class RefreshView(AuthAPIView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "refresh"

    def post(self, request):
        refresh = rotate_refresh(request.COOKIES.get(settings.JWT_REFRESH_COOKIE))
        return set_auth_cookies(
            Response({"detail": "Đã gia hạn phiên đăng nhập."}), request, refresh
        )


class LogoutView(AuthAPIView):
    def post(self, request):
        revoke_refresh(request.COOKIES.get(settings.JWT_REFRESH_COOKIE))
        rotate_token(request)
        return clear_auth_cookies(Response(status=204), request)


class CurrentUserView(APIView):
    # Inherits the project's cookie-JWT-only authentication and IsAuthenticated.
    def get(self, request):
        response = Response(CurrentUserSerializer(request.user).data)
        response["Cache-Control"] = "no-store"
        return response
