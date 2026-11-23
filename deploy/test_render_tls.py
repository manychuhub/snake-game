"""Regression checks for Render CA files and the two runtime service users."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from psycopg.conninfo import conninfo_to_dict

from run import render_database


class RenderTrustTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory(prefix='render-ca-test-')))
        self.directory.chmod(0o711)
        self.destination = self.directory / 'runtime'
        self.destination.mkdir(mode=0o711)
        private = self.directory / 'secrets'
        private.mkdir(mode=0o700)
        self.source = private / 'database.crt'
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Render regression test CA')])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                       .public_key(key.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
                       .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                       .sign(key, hashes.SHA256()))
        self.pem = certificate.public_bytes(serialization.Encoding.PEM).decode('ascii')
        self.source.write_text(self.pem, encoding='ascii')
        self.source.chmod(0o600)
        self.dsn = 'host=db.example.test dbname=test user=runtime password=synthetic sslmode=verify-full'

    def test_dsn_ca_is_staged_without_changing_connection_credentials(self):
        from psycopg.conninfo import make_conninfo
        configured = make_conninfo(self.dsn, sslrootcert=str(self.source))
        result = conninfo_to_dict(render_database(configured, {}, self.destination))
        self.assertEqual(result.pop('sslrootcert'), str(next(self.destination.iterdir())))
        self.assertEqual(result, conninfo_to_dict(self.dsn))

    def test_environment_ca_is_made_explicit_in_both_service_connections(self):
        for _ in (10001, 10002):
            configured = render_database(self.dsn, {'PGSSLROOTCERT': str(self.source)}, self.destination)
            staged = Path(conninfo_to_dict(configured)['sslrootcert'])
            self.assertNotEqual(staged, self.source)
            self.assertEqual(staged.read_text(encoding='ascii'), self.pem)
            ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cafile=str(staged))

    @unittest.skipUnless(hasattr(os, 'geteuid') and os.geteuid() == 0, 'Requires the Linux root container')
    def test_both_service_users_can_load_ca_after_privilege_drop(self):
        probe = (
            'import ssl,sys; '
            'ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cafile=sys.argv[1])'
        )
        for uid in (10001, 10002):
            configured = render_database(self.dsn, {'PGSSLROOTCERT': str(self.source)}, self.destination)
            staged = conninfo_to_dict(configured)['sslrootcert']
            denied = subprocess.run([sys.executable, '-c', 'import sys; open(sys.argv[1]).read()', str(self.source)],
                                    user=uid, group=uid, extra_groups=[], capture_output=True)
            self.assertNotEqual(denied.returncode, 0)
            subprocess.run([sys.executable, '-c', probe, staged],
                           user=uid, group=uid, extra_groups=[], check=True)

    def test_pem_environment_supports_certificate_content(self):
        configured = render_database(self.dsn, {}, self.destination, self.pem)
        self.assertEqual(Path(conninfo_to_dict(configured)['sslrootcert']).read_text(encoding='ascii'), self.pem)

    def test_no_custom_ca_uses_system_trust_without_root_home_lookup(self):
        with patch('run.Path.is_file', return_value=False):
            result = render_database(self.dsn, {}, self.destination)
        self.assertEqual(conninfo_to_dict(result)['sslrootcert'], 'system')

    def test_invalid_or_missing_explicit_ca_fails_without_leaking_dsn(self):
        with self.assertRaises(RuntimeError) as error:
            render_database(self.dsn, {'PGSSLROOTCERT': str(self.source) + '.missing'}, self.destination)
        self.assertNotIn('synthetic', str(error.exception))
        for pem in ('not a certificate', '-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----'):
            with self.assertRaises(RuntimeError):
                render_database(self.dsn, {}, self.destination, pem)


if __name__ == '__main__':
    unittest.main()
