from django.db import migrations


def grant_add_topic(apps, schema_editor):
    alias = schema_editor.connection.alias
    group = (
        apps.get_model("auth", "Group")
        .objects.using(alias)
        .filter(name="LECTURER")
        .first()
    )
    if not group:
        return
    content_type, _ = (
        apps.get_model("contenttypes", "ContentType")
        .objects.using(alias)
        .get_or_create(app_label="topics", model="topic")
    )
    permission, _ = (
        apps.get_model("auth", "Permission")
        .objects.using(alias)
        .get_or_create(
            content_type=content_type,
            codename="add_topic",
            defaults={"name": "Can add topic"},
        )
    )
    group.permissions.add(permission)


def revoke_add_topic(apps, schema_editor):
    alias = schema_editor.connection.alias
    group = (
        apps.get_model("auth", "Group")
        .objects.using(alias)
        .filter(name="LECTURER")
        .first()
    )
    if group:
        permissions = (
            apps.get_model("auth", "Permission")
            .objects.using(alias)
            .filter(content_type__app_label="topics", codename="add_topic")
        )
        group.permissions.remove(*permissions)


class Migration(migrations.Migration):
    dependencies = [
        ("topics", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(grant_add_topic, revoke_add_topic)]
