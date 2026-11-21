from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from accounts.authentication import CookieJWTAuthentication
from accounts.models import Role
from registrations.roles import can_register

from .models import Topic
from .parsers import BoundedJSONParser
from .permissions import TopicAccess, visible_topics
from .roles import business_role, can_manage_topic
from .serializers import LecturerSerializer, TopicQuerySerializer, TopicSerializer
from .services import delete_topic


class TopicPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 100


class TopicViewSet(ModelViewSet):
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated, TopicAccess)
    parser_classes = (BoundedJSONParser,)
    serializer_class = TopicSerializer
    pagination_class = TopicPagination
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        queryset = visible_topics(self.request.user)
        if self.action == "list":
            query = self.validated_query()
            if search := query.get("search"):
                queryset = queryset.filter(
                    Q(code__icontains=search) | Q(title__icontains=search)
                )
            if status := query.get("status"):
                queryset = queryset.filter(status=status)
        return queryset

    def validated_query(self):
        query = TopicQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return query.validated_data

    def perform_destroy(self, instance):
        delete_topic(instance)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    @action(detail=False, methods=["get"])
    def capabilities(self, request):
        return Response(
            {
                "role": business_role(request.user),
                "can_create": can_manage_topic(request.user, "add"),
                "can_edit": can_manage_topic(request.user, "change"),
                "can_delete": can_manage_topic(request.user, "delete"),
                "can_register": can_register(request.user),
                "account_management_url": reverse("admin:accounts_user_changelist")
                if business_role(request.user) == Role.ADMIN
                and request.user.is_staff
                and request.user.has_perm("accounts.view_user")
                else None,
                "statuses": [
                    {"value": value, "label": label}
                    for value, label in Topic.Status.choices
                ],
            }
        )

    @action(detail=False, methods=["get"])
    def lecturers(self, request):
        query = self.validated_query()
        users = (
            get_user_model()
            .objects.filter(is_active=True, groups__name=Role.LECTURER)
            .distinct()
            .order_by("full_name", "pk")
        )
        if search := query.get("search"):
            users = users.filter(full_name__icontains=search)
        page = self.paginate_queryset(users)
        return self.get_paginated_response(LecturerSerializer(page, many=True).data)
