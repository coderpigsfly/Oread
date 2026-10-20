"""HTTPS for Oread's pages and API.

api.tls in settings picks how:

    household  (default) Oread makes a small certificate authority of its own
               (keys/household-ca.*) and signs its own certificate with it
               (keys/oread-cert.pem, keys/oread-key.pem). Browsers warn until
               that authority is installed on the device (download it from
               /ca.crt); after that, no warnings. Works with no internet.
    files      a certificate you got elsewhere (Let's Encrypt via DuckDNS or your
               own domain, Tailscale, a reverse proxy's): api.cert_file and
               api.key_file. Renew it the usual way; Oread reloads it on restart.
    off        plain HTTP, only for running behind a reverse proxy that does
               HTTPS (limit the API to the proxy with the permitted addresses).

The household certificate names every address Oread may be reached by:
localhost, the container's name, and api.tls_names (put the server's address
and name there, e.g. [192.168.1.20, myserver]). It is renewed on start when it
has under 30 days left or the names changed. Certificates last 397 days, the
most Safari and Chrome accept.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import os
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .errors import SettingsError

_LOG = logging.getLogger("oread.tls")
CERT_DAYS = 397
CA_YEARS = 10


def setup(cfg: dict) -> dict:
    """What uvicorn needs: {} for plain HTTP, else cert and key file paths (and the CA file)."""
    api = cfg["api"]
    mode = str(api.get("tls", "household")).lower()
    if mode == "off":
        _LOG.warning("HTTPS is off (api.tls: off). Only do this behind a reverse proxy that does HTTPS.")
        return {}
    if mode == "files":
        cert, key = Path(api.get("cert_file") or ""), Path(api.get("key_file") or "")
        for f in (cert, key):
            if not f.is_file():
                raise SettingsError(f"api.tls is 'files' but {f} isn't a file (api.cert_file / api.key_file)")
        _report(cert)
        return {"cert": cert, "key": key}
    if mode != "household":
        raise SettingsError("api.tls must be household, files or off")
    keys = cfg["paths"]["keys"]
    keys.mkdir(parents=True, exist_ok=True)
    ca_cert, ca_key = _household_ca(keys)
    names = _names(api.get("tls_names") or [])
    cert_path, key_path = keys / "oread-cert.pem", keys / "oread-key.pem"
    if _needs_new(cert_path, names):
        _issue(ca_cert, ca_key, names, cert_path, key_path)
        _LOG.info("Made a household certificate for %s", ", ".join(names))
    _report(cert_path)
    return {"cert": cert_path, "key": key_path, "ca": keys / "household-ca.crt"}


def expiry(cert_path: Path) -> dt.datetime | None:
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except (OSError, ValueError):
        return None
    return cert.not_valid_after_utc


def describe(info: dict) -> dict:
    """For the API and pages: how HTTPS is set up and when the certificate runs out."""
    if not info:
        return {"https": False}
    out = {"https": True, "household": "ca" in info}
    when = expiry(info["cert"])
    if when:
        out["expires"] = when.isoformat(timespec="minutes")
        out["days_left"] = (when - dt.datetime.now(dt.timezone.utc)).days
    try:
        cert = x509.load_pem_x509_certificate(info["cert"].read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        out["names"] = [str(n) for n in san.get_values_for_type(x509.DNSName)] + \
                       [str(n) for n in san.get_values_for_type(x509.IPAddress)]
    except (OSError, ValueError, x509.ExtensionNotFound):
        pass
    return out


# ---------- the household authority ----------

def _household_ca(keys: Path):
    crt, key = keys / "household-ca.crt", keys / "household-ca.key"
    if crt.exists() and key.exists():
        return (x509.load_pem_x509_certificate(crt.read_bytes()),
                serialization.load_pem_private_key(key.read_bytes(), password=None))
    private = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Oread household CA ({socket.gethostname()})"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Oread")])
    now = dt.datetime.now(dt.timezone.utc)
    ski = x509.SubjectKeyIdentifier.from_public_key(private.public_key())
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(private.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=365 * CA_YEARS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=True, crl_sign=True,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(ski, critical=False)
            .sign(private, hashes.SHA256()))
    _write_private(key, private.private_bytes(serialization.Encoding.PEM,
                                              serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _LOG.warning("Made Oread's household certificate authority in keys/. Install "
                 "household-ca.crt (or download /ca.crt) on each device to stop browser warnings. "
                 "Back up keys/ apart from data/.")
    return cert, private


def _names(extra: list) -> list[str]:
    names = ["localhost", "127.0.0.1", socket.gethostname(), "oread"]
    for n in extra:
        n = str(n).strip()
        if n and n not in names:
            names.append(n)
    return names


def _needs_new(cert_path: Path, names: list[str]) -> bool:
    if not cert_path.exists():
        return True
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except (ValueError, x509.ExtensionNotFound):
        return True
    have = {str(v) for v in san.get_values_for_type(x509.DNSName)} | \
           {str(v) for v in san.get_values_for_type(x509.IPAddress)}
    left = cert.not_valid_after_utc - dt.datetime.now(dt.timezone.utc)
    return have != set(names) or left < dt.timedelta(days=30)


def _issue(ca_cert, ca_key, names: list[str], cert_path: Path, key_path: Path) -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    alt = []
    for n in names:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            alt.append(x509.DNSName(n))
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[-1])]))
            .issuer_name(ca_cert.subject)
            .public_key(private.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=CERT_DAYS))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(private.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                           critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_private(key_path, private.private_bytes(serialization.Encoding.PEM,
                                                   serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
    # the server certificate, then the authority, so clients get the whole chain
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM)
                          + ca_cert.public_bytes(serialization.Encoding.PEM))


def _write_private(path: Path, data: bytes) -> None:
    old = os.umask(0o077)
    try:
        path.write_bytes(data)
    finally:
        os.umask(old)
    path.chmod(0o600)


def _report(cert_path: Path) -> None:
    when = expiry(cert_path)
    if when is None:
        return
    days = (when - dt.datetime.now(dt.timezone.utc)).days
    log = _LOG.warning if days < 14 else _LOG.info
    log("HTTPS certificate runs out %s (%d days)", when.date().isoformat(), days)
