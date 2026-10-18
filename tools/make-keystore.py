"""Create the APK signing keystore (PKCS12) without a JDK.

    backend/.venv/Scripts/python tools/make-keystore.py [out_dir]

Writes release.p12, release.p12.b64 (paste into the KEYSTORE_B64 GitHub secret) and password.txt
(KEYSTORE_PASSWORD secret). Keep out_dir backed up in your password manager: losing it means
future APKs can't install over the old one.
"""
import base64
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
out.mkdir(parents=True, exist_ok=True)
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
(out / "release.p12").write_bytes(p12)
(out / "release.p12.b64").write_text(base64.b64encode(p12).decode())
(out / "password.txt").write_text(password)
print(f"Wrote keystore to {out}. Alias: flybye")
print("SHA-1 for Firebase (Android app):", cert.fingerprint(hashes.SHA1()).hex(":").upper())
