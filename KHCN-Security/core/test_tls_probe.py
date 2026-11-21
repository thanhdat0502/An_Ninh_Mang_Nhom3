import ssl
from unittest.mock import patch

from django.test import SimpleTestCase

from scripts.check_tls import default_trust_status


class TLSProbeTrustTests(SimpleTestCase):
    def test_ca_installed_by_user_is_accepted_with_matching_certificate(self):
        with patch(
            "scripts.check_tls.handshake",
            return_value={"certificate_sha256": "expected"},
        ):
            self.assertEqual(default_trust_status("expected"), {"trusted": True})

    def test_untrusted_ca_is_reported_without_disabling_verification(self):
        error = ssl.SSLCertVerificationError(1, "test-only untrusted CA")
        error.verify_code = 19
        with patch("scripts.check_tls.handshake", side_effect=error):
            self.assertEqual(
                default_trust_status("expected"), {"trusted": False, "verify_code": 19}
            )

    def test_different_certificate_does_not_pass(self):
        with (
            patch(
                "scripts.check_tls.handshake",
                return_value={"certificate_sha256": "different"},
            ),
            self.assertRaises(RuntimeError),
        ):
            default_trust_status("expected")

    def test_connection_error_is_not_misreported_as_untrusted_ca(self):
        with (
            patch("scripts.check_tls.handshake", side_effect=ConnectionRefusedError),
            self.assertRaises(ConnectionRefusedError),
        ):
            default_trust_status("expected")
