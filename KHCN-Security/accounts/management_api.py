"""Small JWT-protected adapter for existing account model and permissions."""

from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from topics.api_views import TopicPagination
from topics.parsers import BoundedJSONParser
from topics.roles import business_role

from .authentication import CookieJWTAuthentication
from .management_serializers import (
    AccountQuerySerializer,
    AccountSerializer,
    AccountUpdateSerializer,
)
from .management_services import update_account
from .models import Role, User


class AccountAccess(BasePermission):
    message = "Bạn không có quyền quản lý tài khoản."

    def has_permission(self, request, view):
        user = request.user
        if business_role(user) != Role.ADMIN or not user.has_perm("accounts.view_user"):
            return False
        return view.action != "partial_update" or user.has_perm("accounts.change_user")


class AccountViewSet(GenericViewSet):
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated, AccountAccess)
    parser_classes = (BoundedJSONParser,)
    serializer_class = AccountSerializer
    pagination_class = TopicPagination
    lookup_value_regex = "[0-9]+"
    http_method_names = ("get", "patch", "head", "options")

    def get_queryset(self):
        return User.objects.prefetch_related("groups").order_by("email", "pk")

    def list(self, request):
        query = AccountQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        users = self.get_queryset()
        if search := values.get("search"):
            users = users.filter(
                Q(email__icontains=search) | Q(full_name__icontains=search)
            )
        if role := values.get("role"):
            users = users.filter(groups__name=role).distinct()
        if active := values.get("active"):
            users = users.filter(is_active=active == "true")
        page = self.paginate_queryset(users)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    def partial_update(self, request, pk=None):
        payload = AccountUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user = update_account(
            actor=request.user, account_id=pk, changes=payload.validated_data
        )
        return Response(self.get_serializer(user).data)

    @action(detail=False, methods=["get"])
    def capabilities(self, request):
        return Response({"can_edit": request.user.has_perm("accounts.change_user")})

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
