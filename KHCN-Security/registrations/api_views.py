from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from accounts.authentication import CookieJWTAuthentication
from topics.api_views import TopicPagination
from topics.parsers import BoundedJSONParser
from topics.roles import business_role

from .models import Registration
from .permissions import RegistrationAccess, visible_registrations
from .roles import can_register, can_review
from .serializers import (
    RegistrationCreateSerializer,
    RegistrationQuerySerializer,
    RegistrationSerializer,
    ReviewInputSerializer,
)
from .services import register_for_topic, review_registration


class RegistrationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, GenericViewSet
):
    authentication_classes = (CookieJWTAuthentication,)
    permission_classes = (IsAuthenticated, RegistrationAccess)
    parser_classes = (BoundedJSONParser,)
    pagination_class = TopicPagination
    serializer_class = RegistrationSerializer
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        queryset = visible_registrations(self.request.user)
        if self.action == "list":
            query = RegistrationQuerySerializer(data=self.request.query_params)
            query.is_valid(raise_exception=True)
            for field in ("status", "topic", "student"):
                if value := query.validated_data.get(field):
                    queryset = queryset.filter(**{field: value})
        return queryset

    def create(self, request):
        payload = RegistrationCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        registration = register_for_topic(
            student=request.user, topic_id=payload.validated_data["topic"]
        )
        return Response(
            self.get_serializer(registration).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self.decide(request, Registration.Status.APPROVED)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self.decide(request, Registration.Status.REJECTED)

    def decide(self, request, decision):
        registration = self.get_object()
        payload = ReviewInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        updated = review_registration(
            reviewer=request.user, registration_id=registration.pk, decision=decision
        )
        return Response(self.get_serializer(updated).data)

    @action(detail=False, methods=["get"])
    def capabilities(self, request):
        return Response(
            {
                "role": business_role(request.user),
                "can_register": can_register(request.user),
                "can_review": can_review(request.user),
                "statuses": [
                    {"value": value, "label": label}
                    for value, label in Registration.Status.choices
                ],
            }
        )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
