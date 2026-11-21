"""Token lifecycle operations; refresh/logout share a PostgreSQL row lock."""

from django.db import transaction
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from .authentication import CookieJWTAuthentication


@transaction.atomic
def issue_tokens(user, previous_refresh=None):
    if not user.is_active:
        raise InvalidToken("Tài khoản không hoạt động.")
    revoke_refresh(previous_refresh)
    return RefreshToken.for_user(user)


@transaction.atomic
def rotate_refresh(raw_token):
    if not raw_token:
        raise InvalidToken("Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
    try:
        refresh = RefreshToken(raw_token)
        # Lock the issued token, then recheck blacklist after waiting for a rival
        # refresh/logout transaction. A token can be rotated only once.
        OutstandingToken.objects.select_for_update().get(jti=refresh["jti"])
        refresh.check_blacklist()
        user = CookieJWTAuthentication().get_user(refresh)
        refresh.blacklist()
        return RefreshToken.for_user(user)
    except (TokenError, OutstandingToken.DoesNotExist) as exc:
        raise InvalidToken("Phiên đăng nhập không hợp lệ hoặc đã hết hạn.") from exc


@transaction.atomic
def revoke_refresh(raw_token):
    if not raw_token:
        return
    try:
        refresh = RefreshToken(raw_token)
        OutstandingToken.objects.select_for_update().get(jti=refresh["jti"])
        refresh.blacklist()
    except (TokenError, OutstandingToken.DoesNotExist):
        # Logout remains idempotent when the cookie is invalid, expired or
        # already revoked. Browser cookies are still cleared by the view.
        return
