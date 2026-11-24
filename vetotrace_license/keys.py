"""Gestion de la paire de clés Ed25519 de l'éditeur."""

import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PASSWORD_ENV = 'VETOTRACE_KEY_PASSWORD'


class KeyError_(Exception):
    """Erreur de clé (introuvable, mot de passe, format)."""


def generate(private_path: Path, public_path: Path, password: str | None = None,
             force: bool = False) -> Ed25519PrivateKey:
    if private_path.exists() and not force:
        raise KeyError_(
            f'{private_path} existe déjà. En régénérer une invaliderait TOUTES les '
            'licences émises. Relancer avec --force seulement si c’est voulu.'
        )
    private_path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    encryption = (
        serialization.BestAvailableEncryption(password.encode('utf-8'))
        if password else serialization.NoEncryption()
    )
    private_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption
    ))
    try:
        os.chmod(private_path, 0o600)
    except OSError:
        pass
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_bytes(public_pem(key))
    return key


def is_encrypted(private_path: Path) -> bool:
    return b'ENCRYPTED' in private_path.read_bytes()[:64]


def load_private(private_path: Path, password: str | None = None) -> Ed25519PrivateKey:
    if not private_path.exists():
        raise KeyError_(f'Clé privée introuvable : {private_path}. Lancer d’abord « keygen ».')
    if password is None:
        password = os.environ.get(PASSWORD_ENV)
    try:
        key = serialization.load_pem_private_key(
            private_path.read_bytes(),
            password=password.encode('utf-8') if password else None,
        )
    except TypeError as exc:
        raise KeyError_('Clé privée chiffrée : mot de passe requis.') from exc
    except ValueError as exc:
        raise KeyError_('Mot de passe incorrect ou clé privée illisible.') from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise KeyError_('La clé privée n’est pas une clé Ed25519.')
    return key


def public_pem(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def fingerprint(public_key_pem: bytes) -> str:
    """Empreinte courte (SHA-256 de la clé publique brute) pour contrôler que
    l'application embarque bien la bonne clé publique."""
    pub = serialization.load_pem_public_key(public_key_pem)
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    digest = hashlib.sha256(raw).hexdigest()[:32]
    return ':'.join(digest[i:i + 4] for i in range(0, 32, 4))
