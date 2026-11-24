"""VétoTrace - outil éditeur de génération des licences de poste (bureau).

Outil INTERNE à l'éditeur, volontairement hors du dépôt applicatif : il
manipule la clé privée qui signe les licences. Ne jamais le distribuer avec
l'application, ne jamais commiter la clé privée.

Commandes :
    keygen     crée la paire de clés Ed25519 (une seule fois)
    pubkey     réexporte la clé publique (à copier dans l'application)
    issue      émet une clé de licence
    verify     décode et vérifie une clé (support client)

Exemples :
    python vetotrace_license.py keygen
    python vetotrace_license.py issue --licensee "Clinique des Palmiers" \
        --expires 2027-12-31 --machine-id 1a2b3c4d-...
    python vetotrace_license.py verify <clé>

La clé publique doit être copiée dans
    veto_track_api/apps/desktop/license_public_key.pem
du dépôt VétoTrace avant de compiler l'application.
"""

import argparse
import base64
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HOME = Path.home() / '.vetotrace'
DEFAULT_PRIVATE = HOME / 'license_private.pem'
DEFAULT_PUBLIC = HOME / 'license_public_key.pem'
REGISTER = HOME / 'licences_emises.csv'

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def load_private(path):
    path = Path(path)
    if not path.exists():
        sys.exit(f'Clé privée introuvable : {path}. Lancer d’abord « keygen ».')
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def public_pem(private_key) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def cmd_keygen(args):
    private_path = Path(args.private_key)
    if private_path.exists() and not args.force:
        sys.exit(
            f'{private_path} existe déjà. En régénérer une invaliderait TOUTES les '
            'licences émises. Relancer avec --force seulement si c’est voulu.'
        )
    private_path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    Path(args.public_out).write_bytes(public_pem(key))
    print(f'Clé privée   : {private_path}  -> à sauvegarder hors ligne, en lieu sûr')
    print(f'Clé publique : {args.public_out}  -> à copier dans l’application')


def cmd_pubkey(args):
    pem = public_pem(load_private(args.private_key))
    if args.out:
        Path(args.out).write_bytes(pem)
        print(f'Clé publique écrite : {args.out}')
    else:
        print(pem.decode('ascii'), end='')


def cmd_issue(args):
    key = load_private(args.private_key)
    if args.expires:
        try:
            if date.fromisoformat(args.expires) < date.today():
                sys.exit('La date d’expiration est déjà passée.')
        except ValueError:
            sys.exit('Format de date attendu : AAAA-MM-JJ.')
    payload = {
        'v': 1,
        'licensee': args.licensee,
        'expires': args.expires,
        'machine_id': args.machine_id,
        'issued': date.today().isoformat(),
    }
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    licence = f'{b64(raw)}.{b64(key.sign(raw))}'

    REGISTER.parent.mkdir(parents=True, exist_ok=True)
    new_file = not REGISTER.exists()
    with REGISTER.open('a', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh, delimiter=';')
        if new_file:
            writer.writerow(['emise_le', 'titulaire', 'expire', 'poste', 'cle'])
        writer.writerow(
            [
                datetime.now().isoformat(timespec='seconds'),
                args.licensee,
                args.expires or 'illimitée',
                args.machine_id or 'tout poste',
                licence,
            ]
        )
    print(licence)
    print(f'\n(enregistrée dans {REGISTER})', file=sys.stderr)


def cmd_verify(args):
    key = load_private(args.private_key)
    try:
        payload_b64, sig_b64 = args.key.strip().split('.')
        raw = unb64(payload_b64)
        key.public_key().verify(unb64(sig_b64), raw)
    except InvalidSignature:
        sys.exit('Signature INVALIDE (clé modifiée ou émise par une autre paire).')
    except ValueError:
        sys.exit('Clé illisible.')
    payload = json.loads(raw)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    expires = payload.get('expires')
    if expires and date.fromisoformat(expires) < date.today():
        print('-> signature valide mais licence EXPIRÉE')
    else:
        print('-> licence valide')


def main():
    parser = argparse.ArgumentParser(
        description='Générateur de licences VétoTrace (bureau)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--private-key', default=str(DEFAULT_PRIVATE))
    sub = parser.add_subparsers(dest='cmd', required=True)

    k = sub.add_parser('keygen', help='créer la paire de clés')
    k.add_argument('--public-out', default=str(DEFAULT_PUBLIC))
    k.add_argument('--force', action='store_true')
    k.set_defaults(func=cmd_keygen)

    p = sub.add_parser('pubkey', help='exporter la clé publique')
    p.add_argument('--out')
    p.set_defaults(func=cmd_pubkey)

    i = sub.add_parser('issue', help='émettre une licence')
    i.add_argument('--licensee', required=True, help='nom de la clinique titulaire')
    i.add_argument('--expires', help='AAAA-MM-JJ ; omis = sans expiration')
    i.add_argument('--machine-id', help='identifiant affiché sur l’écran d’activation')
    i.set_defaults(func=cmd_issue)

    v = sub.add_parser('verify', help='vérifier une licence')
    v.add_argument('key')
    v.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
