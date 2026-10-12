"""SSLv3 для FESL: игра 2006 года понимает только SSLv3 + RC4.

Современный OpenSSL SSLv3 не умеет, поэтому используется tlslite-ng (чистый Python).
Проверка сертификата в клиенте отключена, но разбирать его клиент всё равно
будет, поэтому сертификат «по-старому»: RSA-1024 с подписью sha1WithRSA.
"""

import datetime
import logging
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from tlslite.api import HandshakeSettings, X509, X509CertChain, parsePEMKey

log = logging.getLogger("tls")

_OID_SHA256_RSA = bytes.fromhex("06092A864886F70D01010B")
_OID_SHA1_RSA = bytes.fromhex("06092A864886F70D010105")


def _make_cert(cert_path: Path, key_path: Path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Electronic Arts, Inc."),
        x509.NameAttribute(NameOID.COMMON_NAME, "bf2142-pc.fesl.ea.com"),
    ])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    # cryptography больше не подписывает SHA-1, поэтому меняем OID алгоритма
    # (той же длины) и переподписываем TBS вручную.
    der = cert.public_bytes(serialization.Encoding.DER)
    tbs = cert.tbs_certificate_bytes.replace(_OID_SHA256_RSA, _OID_SHA1_RSA)
    signature = key.sign(tbs, padding.PKCS1v15(), hashes.SHA1())
    der = der.replace(_OID_SHA256_RSA, _OID_SHA1_RSA).replace(cert.signature, signature)
    pem = x509.load_der_x509_certificate(der).public_bytes(serialization.Encoding.PEM)

    cert_path.write_bytes(pem)
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ))
    log.info("создан сертификат FESL: %s", cert_path)


class ServerCredentials:
    def __init__(self, data_dir: Path):
        cert_path, key_path = data_dir / "fesl_cert.pem", data_dir / "fesl_key.pem"
        if not (cert_path.exists() and key_path.exists()):
            _make_cert(cert_path, key_path)
        cert = X509()
        cert.parse(cert_path.read_text())
        self.chain = X509CertChain([cert])
        self.key = parsePEMKey(key_path.read_text(), private=True)
        settings = HandshakeSettings()
        settings.minVersion = (3, 0)
        settings.maxVersion = (3, 1)
        settings.cipherNames = ["rc4", "aes128", "3des"]
        settings.macNames = ["sha", "md5"]
        settings.keyExchangeNames = ["rsa"]
        self.settings = settings.validate()
