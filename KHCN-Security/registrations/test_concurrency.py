from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from accounts.models import Role
from topics.models import Topic
from topics.roles import sync_topic_permissions

from .models import Registration
from .roles import sync_registration_permissions
from .services import RegistrationConflict, register_for_topic, review_registration

User = get_user_model()


class RegistrationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        sync_topic_permissions()
        sync_registration_permissions()
        self.student = User.objects.create_user(
            "race-student@example.com", full_name="Sinh viên"
        )
        self.lecturer = User.objects.create_user(
            "race-lecturer@example.com", full_name="Giảng viên"
        )
        self.admin = User.objects.create_user(
            "race-admin@example.com", full_name="Quản trị viên"
        )
        for user, role in (
            (self.student, Role.STUDENT),
            (self.lecturer, Role.LECTURER),
            (self.admin, Role.ADMIN),
        ):
            user.groups.add(Group.objects.get(name=role))
        self.topic = Topic.objects.create(
            code="RACE-001",
            title="Kiểm thử cạnh tranh",
            description="Mô tả",
            lecturer=self.lecturer,
            status=Topic.Status.OPEN,
        )

    def run_workers(self, operations):
        barrier = Barrier(2)

        def worker(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, operations))

    def test_two_simultaneous_registration_attempts_create_one_record(self):
        def attempt():
            try:
                register_for_topic(
                    student=User.objects.get(pk=self.student.pk), topic_id=self.topic.pk
                )
                return "created"
            except RegistrationConflict:
                return "conflict"

        results = self.run_workers((attempt, attempt))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("conflict"), 1)
        self.assertEqual(Registration.objects.count(), 1)

    def test_simultaneous_approve_and_reject_have_one_winner_with_correct_audit(self):
        registration = Registration.objects.create(
            student=self.student, topic=self.topic
        )

        def attempt(user_id, decision):
            def operation():
                try:
                    review_registration(
                        reviewer=User.objects.get(pk=user_id),
                        registration_id=registration.pk,
                        decision=decision,
                    )
                    return "reviewed", user_id, decision
                except RegistrationConflict:
                    return "conflict", user_id, decision

            return operation

        results = self.run_workers(
            (
                attempt(self.lecturer.pk, Registration.Status.APPROVED),
                attempt(self.admin.pk, Registration.Status.REJECTED),
            )
        )
        winners = [item for item in results if item[0] == "reviewed"]
        self.assertEqual(len(winners), 1)
        self.assertEqual(sum(item[0] == "conflict" for item in results), 1)
        registration.refresh_from_db()
        self.assertEqual(registration.reviewed_by_id, winners[0][1])
        self.assertEqual(registration.status, winners[0][2])
        self.assertIsNotNone(registration.reviewed_at)
