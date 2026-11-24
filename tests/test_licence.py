import json
from datetime import date

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vetotrace_license import cli, keys
from vetotrace_license.catalog import FEATURES, load_plans
from vetotrace_license.dates import add_months, compute_end_date
from vetotrace_license.licence import (
    IssueRequest,
    b64,
    build_payload,
    sign,
    unb64,
    verify,
)
from vetotrace_license.pricing import calculate_price
from vetotrace_license.register import LEGACY_COLUMNS, Register

PLANS = load_plans()


def _req(**kw):
    base = dict(licensee='Clinique Test', plan=PLANS['vetotrace-solo'], cycle='yearly',
                starts=date(2026, 1, 31), licence_id='VT-TEST-0001',
                issued=date(2026, 1, 31))
    base.update(kw)
    return IssueRequest(**base)


# ─── catalogue (aligné sur create_plan_fixtures) ─────────────────────────
def test_catalogue_matches_fixtures():
    assert len(PLANS) == 7
    solo = PLANS['vetotrace-solo']
    assert (solo.max_users, solo.price_yearly, solo.setup_fee) == (1, 150_000, 20_000)
    assert [f for f in FEATURES if solo.features[f]] == [
        'has_hospitalization', 'has_export_excel']
    assert all(PLANS['vetotrace-entreprise'].features.values())
    para = PLANS['vetotrace-parapharmacie']
    assert not para.features['has_hospitalization']
    pub = PLANS['vetotrace-public']
    assert not pub.features['has_whatsapp_notif'] and pub.features['has_api_access']


def test_plans_override(tmp_path):
    f = tmp_path / 'plans.json'
    f.write_text(json.dumps([{'slug': 'vetotrace-solo', 'max_users': 2},
                             {'slug': 'x', 'name': 'X', 'structure_type': 'custom',
                              'price_monthly': 1, 'price_quarterly': 1, 'price_yearly': 1,
                              'price_lifetime': 0, 'setup_fee': 0, 'max_users': 3,
                              'extra_user_price': 0, 'max_clinics': 1, 'max_animals': 0,
                              'max_storage_mb': 0, 'features': {'has_api_access': True}}]))
    plans = load_plans(f)
    assert plans['vetotrace-solo'].max_users == 2
    assert plans['vetotrace-solo'].price_yearly == 150_000
    assert plans['x'].features['has_api_access'] and not plans['x'].features['has_lab_module']


# ─── dates et prix (alignés sur licensing/services.py) ───────────────────
def test_end_dates():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert compute_end_date(date(2026, 11, 30), 'quarterly') == date(2027, 2, 28)
    assert compute_end_date(date(2026, 1, 1), 'lifetime') is None
    assert compute_end_date(date(2026, 1, 1), 'trial', 30) == date(2026, 1, 31)


def test_price():
    d = calculate_price(PLANS['vetotrace-petite-clinique'], 'yearly', extra_users=2,
                        discount_percent=10)
    assert d['extra_users_price'] == 2 * 7_000 * 12
    assert d['discount'] == 52_800
    assert d['total'] == 360_000 + 168_000 - 52_800 + 30_000


# ─── payload ─────────────────────────────────────────────────────────────
def test_payload_v2():
    p = build_payload(_req(extra_users=2))
    assert p['v'] == 2 and p['plan'] == 'vetotrace-solo'
    assert p['expires'] == '2027-01-31' and p['grace_days'] == 7
    assert p['limits'] == {'users': 3, 'clinics': 1, 'animals': 0, 'storage_mb': 500}
    assert list(p['features']) == list(FEATURES)


def test_enterprise_unlimited():
    p = build_payload(_req(plan=PLANS['vetotrace-entreprise'], extra_users=5))
    assert p['limits']['users'] == 0 and p['limits']['clinics'] == 0


def test_feature_overrides():
    p = build_payload(_req(enable=('has_lab_module',), disable=('has_export_excel',)))
    assert p['features']['has_lab_module'] and not p['features']['has_export_excel']
    with pytest.raises(ValueError):
        build_payload(_req(enable=('has_lab_module',), disable=('has_lab_module',)))
    with pytest.raises(ValueError):
        build_payload(_req(enable=('inconnu',)))


def test_multi_clinic_requires_flag():
    with pytest.raises(ValueError):
        build_payload(_req(clinics=3))
    assert build_payload(_req(clinics=3, enable=('has_multi_clinic',)))['limits']['clinics'] == 3


def test_lifetime_and_trial_have_no_grace():
    assert build_payload(_req(cycle='lifetime'))['expires'] is None
    t = build_payload(_req(cycle='trial', trial_days=14))
    assert t['expires'] == '2026-02-14' and t['grace_days'] == 0


# ─── signature / vérification ────────────────────────────────────────────
def test_sign_verify_states():
    priv = Ed25519PrivateKey.generate()
    key = sign(build_payload(_req()), priv)
    pub = priv.public_key()
    assert verify(key, pub, date(2026, 6, 1)).state == 'valide'
    assert verify(key, pub, date(2027, 2, 3)).state == 'grace'
    assert verify(key, pub, date(2027, 2, 8)).state == 'expiree'
    assert verify(key, pub, date(2026, 1, 1)).state == 'future'


def test_tampering_and_foreign_signer_refused():
    priv = Ed25519PrivateKey.generate()
    payload_b64, sig = sign(build_payload(_req()), priv).split('.')
    forged = json.loads(unb64(payload_b64))
    forged['limits']['users'] = 0
    forged_b64 = b64(json.dumps(forged).encode())
    assert not verify(f'{forged_b64}.{sig}', priv.public_key()).signature_ok
    other = Ed25519PrivateKey.generate()
    assert not verify(sign(build_payload(_req()), other), priv.public_key()).signature_ok
    assert verify('n.importe', priv.public_key()).state == 'invalide'


def test_v1_still_readable():
    priv = Ed25519PrivateKey.generate()
    raw = json.dumps({'v': 1, 'licensee': 'Ancienne', 'expires': None,
                      'machine_id': None}).encode()
    key = f'{b64(raw)}.{b64(priv.sign(raw))}'
    assert verify(key, priv.public_key()).usable


# ─── clés ────────────────────────────────────────────────────────────────
def test_encrypted_private_key(tmp_path):
    keys.generate(tmp_path / 'p.pem', tmp_path / 'pub.pem', password='motdepasse-long')
    assert keys.is_encrypted(tmp_path / 'p.pem')
    with pytest.raises(keys.KeyError_):
        keys.load_private(tmp_path / 'p.pem', 'mauvais')
    keys.load_private(tmp_path / 'p.pem', 'motdepasse-long')
    with pytest.raises(keys.KeyError_):
        keys.generate(tmp_path / 'p.pem', tmp_path / 'pub.pem')
    assert len(keys.fingerprint((tmp_path / 'pub.pem').read_bytes())) == 39


# ─── registre ────────────────────────────────────────────────────────────
def test_register_migrates_v1(tmp_path):
    path = tmp_path / 'licences_emises.csv'
    path.write_text(';'.join(LEGACY_COLUMNS) + '\n2026-11-23T10:00:00;Clinique A;'
                    'illimitée;tout poste;abc.def\n', encoding='utf-8')
    reg = Register(path)
    entries = reg.entries()
    assert entries[0]['id'] == 'V1-0001' and entries[0]['cle'] == 'abc.def'
    assert path.with_suffix('.v1.bak').exists()
    assert reg.next_id(date(2026, 11, 24)) == 'VT-20261124-0001'


# ─── bout en bout (CLI) ──────────────────────────────────────────────────
def _run(tmp_path, capsys, *argv):
    cli.main(['--home', str(tmp_path), *argv])
    return capsys.readouterr().out.strip().splitlines()[-1]


def test_cli_issue_renew_upgrade(tmp_path, capsys):
    cli.main(['--home', str(tmp_path), 'keygen'])
    capsys.readouterr()
    key = _run(tmp_path, capsys, 'issue', '--licensee', 'Clinique B', '--plan', 'solo',
               '--extra-users', '1', '--enable', 'has_lab_module')
    pub = keys.load_private(tmp_path / 'license_private.pem').public_key()
    first = verify(key, pub).payload
    assert first['limits']['users'] == 2 and first['features']['has_lab_module']

    renewed = verify(_run(tmp_path, capsys, 'renew', first['id']), pub).payload
    assert renewed['starts'] == first['expires']
    assert renewed['limits'] == first['limits'] and renewed['features'] == first['features']
    assert renewed['id'] != first['id']

    up = verify(_run(tmp_path, capsys, 'upgrade', first['id'], '--plan', 'clinique-moyenne'),
                pub).payload
    assert up['plan'] == 'vetotrace-clinique-moyenne' and up['limits']['users'] == 15

    cli.main(['--home', str(tmp_path), 'list'])
    assert len(capsys.readouterr().out.strip().splitlines()) == 3


def test_cli_unknown_plan(tmp_path):
    cli.main(['--home', str(tmp_path), 'keygen'])
    with pytest.raises(SystemExit) as exc:
        cli.main(['--home', str(tmp_path), 'issue', '--licensee', 'X', '--plan', 'nope'])
    assert exc.value.code == 2
