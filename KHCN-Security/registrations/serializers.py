from collections.abc import Mapping

from rest_framework import serializers

from .models import Registration


class StrictInputSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, Mapping) and set(data) - set(self.fields):
            raise serializers.ValidationError(
                {"non_field_errors": ["Yêu cầu chứa trường không được phép gửi."]}
            )
        return super().to_internal_value(data)


class RegistrationCreateSerializer(StrictInputSerializer):
    topic = serializers.IntegerField(min_value=1)


class ReviewInputSerializer(StrictInputSerializer):
    pass


class RegistrationSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    student_email = serializers.EmailField(source="student.email", read_only=True)
    topic_code = serializers.CharField(source="topic.code", read_only=True)
    topic_title = serializers.CharField(source="topic.title", read_only=True)
    lecturer_name = serializers.CharField(
        source="topic.lecturer.full_name", read_only=True
    )
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    reviewer_name = serializers.CharField(
        source="reviewed_by.full_name", read_only=True, allow_null=True
    )

    class Meta:
        model = Registration
        fields = (
            "id",
            "student",
            "student_name",
            "student_email",
            "topic",
            "topic_code",
            "topic_title",
            "lecturer_name",
            "status",
            "status_label",
            "created_at",
            "updated_at",
            "reviewed_by",
            "reviewer_name",
            "reviewed_at",
        )
        read_only_fields = fields


class RegistrationQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=Registration.Status.choices, required=False, allow_blank=True
    )
    topic = serializers.IntegerField(min_value=1, required=False)
    student = serializers.IntegerField(min_value=1, required=False)
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)
