"""Limited account editing for the business interface; never grant privileges."""

from collections.abc import Mapping

from rest_framework import serializers

from .models import Role, User


class AccountQuerySerializer(serializers.Serializer):
    search = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=Role.choices, required=False, allow_blank=True
    )
    active = serializers.ChoiceField(
        choices=("true", "false", ""), required=False, allow_blank=True
    )
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class AccountSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "is_active", "roles", "can_edit")
        read_only_fields = fields

    def get_roles(self, user):
        return [group.name for group in user.groups.all() if group.name in Role.values]

    def get_can_edit(self, user):
        actor = self.context["request"].user
        return actor.has_perm("accounts.change_user") and (
            not user.is_superuser or actor.is_superuser
        )


class AccountUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254, required=False)
    full_name = serializers.CharField(max_length=150, required=False)
    is_active = serializers.BooleanField(required=False)

    def to_internal_value(self, data):
        if isinstance(data, Mapping) and set(data) - set(self.fields):
            raise serializers.ValidationError(
                {"non_field_errors": ["Yêu cầu chứa trường không được phép sửa."]}
            )
        return super().to_internal_value(data)

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Chưa có thông tin cần cập nhật.")
        return attrs
