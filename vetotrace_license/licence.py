"""Construction, signature et vérification des clés de licence (v1 et v2).

Le format v2 est un contrat avec `veto_track_api/apps/desktop/license.py`
(voir docs/PLAN.md, section 3) : toute modification doit être faite des deux
côtés.
"""

import base64
import json
from dataclasses import dataclass
from datetime import date, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .catalog import CYCLES, FEATURES, Plan, limit
from .dates import TRIAL_DAYS, compute_end_date

VERSION = 2
DEFAULT_GRACE_DAYS = 7


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


@dataclass
class IssueRequest:
    licensee: str
    plan: Plan
    cycle: str
    starts: date
    licence_id: str
    extra_users: int = 0
    clinics: int | None = None
    enable: tuple = ()
    disable: tuple = ()
    machine_id: str | None = None
    grace_days: int | None = None
    trial_days: int = TRIAL_DAYS
    issued: date | None = None


def build_payload(req: IssueRequest) -> dict:
    if not req.licensee.strip():
        raise ValueError('Le titulaire est obligatoire.')
    if req.cycle not in (*CYCLES, 'trial'):
        raise ValueError(f'Cycle inconnu : {req.cycle}')
    if req.extra_users < 0:
        raise ValueError('Le nombre d’utilisateurs supplémentaires doit être positif.')
    for flag in (*req.enable, *req.disable):
        if flag not in FEATURES:
            raise ValueError(f'Module inconnu : {flag} (attendus : {", ".join(FEATURES)})')
    if set(req.enable) & set(req.disable):
        raise ValueError('Un module ne peut pas être à la fois activé et désactivé.')

    features = dict(req.plan.features)
    features.update({f: True for f in req.enable})
    features.update({f: False for f in req.disable})

    users = limit(req.plan.max_users)
    if users:
        users += req.extra_users
    clinics = limit(req.plan.max_clinics) if req.clinics is None else int(req.clinics)
    if clinics != 1 and not features['has_multi_clinic']:
        raise ValueError('Plusieurs cliniques exigent le module has_multi_clinic.')

    expires = compute_end_date(req.starts, req.cycle, req.trial_days)
    if req.grace_days is None:
        grace = 0 if req.cycle in ('trial', 'lifetime') else DEFAULT_GRACE_DAYS
    else:
        grace = max(int(req.grace_days), 0)

    return {
        'v': VERSION,
        'id': req.licence_id,
        'licensee': req.licensee.strip(),
        'issued': (req.issued or date.today()).isoformat(),
        'plan': req.plan.slug,
        'plan_name': req.plan.name,
        'edition': req.plan.structure_type,
        'cycle': req.cycle,
        'starts': req.starts.isoformat(),
        'expires': expires.isoformat() if expires else None,
        'grace_days': grace,
        'machine_id': req.machine_id or None,
        'limits': {
            'users': users,
            'clinics': clinics,
            'animals': limit(req.plan.max_animals),
            'storage_mb': limit(req.plan.max_storage_mb),
        },
        'features': {f: bool(features[f]) for f in FEATURES},
    }


def sign(payload: dict, private_key: Ed25519PrivateKey) -> str:
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return f'{b64(raw)}.{b64(private_key.sign(raw))}'


@dataclass
class Verification:
    signature_ok: bool
    payload: dict | None
    state: str  # valide | grace | expiree | future | invalide
    message: str

    @property
    def usable(self) -> bool:
        return self.state in ('valide', 'grace')


def verify(key: str, public_key: Ed25519PublicKey, today: date | None = None) -> Verification:
    today = today or date.today()
    try:
        payload_b64, sig_b64 = key.strip().split('.')
        raw = unb64(payload_b64)
        public_key.verify(unb64(sig_b64), raw)
        payload = json.loads(raw)
    except InvalidSignature:
        return Verification(False, None, 'invalide',
                            'Signature INVALIDE (clé modifiée ou émise par une autre paire).')
    except Exception:
        return Verification(False, None, 'invalide', 'Clé illisible.')

    if payload.get('v') not in (1, 2):
        return Verification(True, payload, 'invalide', 'Version de clé non prise en charge.')
    starts = payload.get('starts')
    if starts and date.fromisoformat(starts) > today:
        return Verification(True, payload, 'future', f'Licence valable à partir du {starts}.')
    expires = payload.get('expires')
    if expires:
        end = date.fromisoformat(expires)
        grace_end = end + timedelta(days=int(payload.get('grace_days') or 0))
        if today > grace_end:
            return Verification(True, payload, 'expiree', f'Licence EXPIRÉE depuis le {expires}.')
        if today > end:
            return Verification(True, payload, 'grace',
                                f'Expirée le {expires}, en période de grâce jusqu’au {grace_end}.')
    return Verification(True, payload, 'valide', 'Licence valide.')
