from collections.abc import Mapping

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from accounts.models import Role

from .models import Topic
from .roles import business_role
from .services import persist_topic


class TopicSerializer(serializers.ModelSerializer):
    code = serializers.RegexField(
        r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$",
        max_length=30,
        validators=[
            UniqueValidator(Topic.objects.all(), message="Mã đề tài đã tồn tại.")
        ],
    )
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(max_length=10000)
    lecturer = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model()
        .objects.filter(
            is_active=True,
            groups__name=Role.LECTURER,
        )
        .distinct()
    )
    lecturer_name = serializers.CharField(source="lecturer.full_name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Topic
        fields = (
            "id",
            "code",
            "title",
            "description",
            "lecturer",
            "lecturer_name",
            "status",
            "status_label",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request and business_role(request.user) == Role.LECTURER:
            fields["lecturer"].required = False
            fields["lecturer"].default = serializers.CurrentUserDefault()
        return fields

    def validate_lecturer(self, lecturer):
        request = self.context.get("request")
        if (
            request
            and business_role(request.user) == Role.LECTURER
            and lecturer.pk != request.user.pk
        ):
            raise serializers.ValidationError(
                "Bạn chỉ có thể thêm đề tài do chính mình phụ trách."
            )
        return lecturer

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            allowed = {
                name for name, field in self.fields.items() if not field.read_only
            }
            unexpected = set(data) - allowed
            if unexpected:
                raise serializers.ValidationError(
                    {
                        "non_field_errors": [
                            "Yêu cầu chứa trường không được phép chỉnh sửa."
                        ]
                    }
                )
        return super().to_internal_value(data)

    def create(self, validated_data):
        return persist_topic(Topic(**validated_data))

    def update(self, instance, validated_data):
        for name, value in validated_data.items():
            setattr(instance, name, value)
        return persist_topic(instance)


class TopicQuerySerializer(serializers.Serializer):
    search = serializers.CharField(max_length=150, required=False, allow_blank=True)
    status = serializers.ChoiceField(
        choices=Topic.Status.choices, required=False, allow_blank=True
    )
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class LecturerSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ("id", "full_name")
        read_only_fields = fields
