"""Create the APK signing keystore (PKCS12) without a JDK.

    backend/.venv/Scripts/python tools/make-keystore.py [out_dir]

Writes release.p12, release.p12.b64 (paste into the KEYSTORE_B64 GitHub secret) and password.txt
(KEYSTORE_PASSWORD secret). Keep out_dir backed up in your password manager: losing it means
future APKs can't install over the old one.
"""
import base64
import os
import datetime as dt
import pathlib
import secrets
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path.home() / "flybye-keystore")
out.mkdir(parents=True, exist_ok=True, mode=0o700)
if (out / "release.p12").exists():
    sys.exit(f"{out / 'release.p12'} already exists; not overwriting")

key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Flybye")])
now = dt.datetime.now(dt.timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=365 * 30)).sign(key, hashes.SHA256()))
password = secrets.token_urlsafe(24)
p12 = pkcs12.serialize_key_and_certificates(b"flybye", key, cert, None,
                                            serialization.BestAvailableEncryption(password.encode()))
def write_secret(path, data):  # owner-only on POSIX; on Windows the home folder is already private to you
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(data)


write_secret(out / "release.p12", p12)
write_secret(out / "release.p12.b64", base64.b64encode(p12))
write_secret(out / "password.txt", password.encode())
print(f"Wrote keystore to {out}. Alias: flybye")
print("SHA-1 for Firebase (Android app):", cert.fingerprint(hashes.SHA1()).hex(":").upper())
