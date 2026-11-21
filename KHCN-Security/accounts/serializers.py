from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed

from .models import Role, User


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=1024,
    )

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            email=attrs["email"],
            password=attrs["password"],
        )
        if user is None or not user.is_active:
            raise AuthenticationFailed("Email hoặc mật khẩu không đúng.")
        return {"user": user}


class CurrentUserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "roles")
        read_only_fields = fields

    def get_roles(self, user):
        return list(
            user.groups.filter(name__in=Role.values)
            .order_by("name")
            .values_list("name", flat=True)
        )
