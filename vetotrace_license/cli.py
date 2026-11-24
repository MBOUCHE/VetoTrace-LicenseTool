"""Interface en ligne de commande du générateur de licences VétoTrace."""

import argparse
import getpass
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_public_key

from . import keys
from .catalog import CYCLE_LABELS, CYCLES, FEATURE_LABELS, FEATURES, load_plans
from .licence import DEFAULT_GRACE_DAYS, IssueRequest, build_payload, sign, verify
from .pricing import calculate_price, fcfa
from .register import Register, payload_of

HOME = Path.home() / '.vetotrace'


class CliError(Exception):
    pass


# ─── utilitaires ─────────────────────────────────────────────────────────
def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Format de date attendu : AAAA-MM-JJ.') from exc


def _plans(args):
    return load_plans(Path(args.home) / 'plans.json')


def _plan(args, slug):
    plans = _plans(args)
    if slug not in plans:
        # Accepte « solo » pour « vetotrace-solo ».
        slug = f'vetotrace-{slug}' if f'vetotrace-{slug}' in plans else slug
    if slug not in plans:
        raise CliError(f'Plan inconnu : {slug}. Voir la commande « plans ».')
    return plans[slug]


def _private(args):
    path = Path(args.private_key)
    password = None
    if path.exists() and keys.is_encrypted(path) and not _env_password():
        password = getpass.getpass('Mot de passe de la clé privée : ')
    try:
        return keys.load_private(path, password)
    except keys.KeyError_ as exc:
        raise CliError(str(exc)) from exc


def _env_password():
    import os

    return os.environ.get(keys.PASSWORD_ENV)


def _register(args) -> Register:
    return Register(Path(args.home) / 'licences_emises.csv')


def _limit(value) -> str:
    return 'illimité' if not value else str(value)


def _describe(payload: dict) -> str:
    lines = [
        f"Licence     : {payload.get('id', '(v1)')}",
        f"Titulaire   : {payload.get('licensee', '')}",
    ]
    if payload.get('v') == 1:
        lines += [
            'Format      : v1 (accès complet, sans plan)',
            f"Expire      : {payload.get('expires') or 'jamais'}",
            f"Poste       : {payload.get('machine_id') or 'tout poste'}",
        ]
        return '\n'.join(lines)
    lim = payload['limits']
    lines += [
        f"Plan        : {payload['plan_name']} ({payload['plan']})",
        f"Cycle       : {CYCLE_LABELS.get(payload['cycle'], payload['cycle'])}",
        f"Période     : {payload['starts']} -> {payload['expires'] or 'perpétuelle'}"
        + (f" (+{payload['grace_days']} j de grâce)" if payload['grace_days'] else ''),
        f"Poste       : {payload['machine_id'] or 'tout poste'}",
        f"Quotas      : {_limit(lim['users'])} utilisateur(s), "
        f"{_limit(lim['clinics'])} clinique(s), stockage {_limit(lim['storage_mb'])} Mo",
        'Modules     : ' + ', '.join(
            FEATURE_LABELS[f] for f in FEATURES if payload['features'].get(f)
        ),
    ]
    return '\n'.join(lines)


def _emit(args, payload, origin=''):
    key = sign(payload, _private(args))
    _register(args).add(payload, key, origin)
    print(_describe(payload), file=sys.stderr)
    print(f"\n(enregistrée dans {_register(args).path})\n", file=sys.stderr)
    if getattr(args, 'out', None):
        Path(args.out).write_text(key, encoding='utf-8')
        print(f'Clé écrite dans {args.out}', file=sys.stderr)
    print(key)


# ─── commandes ───────────────────────────────────────────────────────────
def cmd_keygen(args):
    password = None
    if args.encrypt:
        password = _env_password() or getpass.getpass('Nouveau mot de passe : ')
        if not _env_password() and password != getpass.getpass('Confirmer : '):
            raise CliError('Les mots de passe ne correspondent pas.')
        if len(password) < 12:
            raise CliError('Mot de passe trop court (12 caractères minimum).')
    public_out = Path(args.public_out or Path(args.home) / 'license_public_key.pem')
    try:
        keys.generate(Path(args.private_key), public_out, password, args.force)
    except keys.KeyError_ as exc:
        raise CliError(str(exc)) from exc
    print(f'Clé privée   : {args.private_key}  -> à sauvegarder hors ligne, en lieu sûr')
    print(f'Clé publique : {public_out}  -> à copier dans '
          'veto_track_api/apps/desktop/license_public_key.pem')
    print(f'Empreinte    : {keys.fingerprint(public_out.read_bytes())}')


def cmd_pubkey(args):
    pem = keys.public_pem(_private(args))
    if args.out:
        Path(args.out).write_bytes(pem)
        print(f'Clé publique écrite : {args.out}')
    else:
        print(pem.decode('ascii'), end='')
    print(f'Empreinte : {keys.fingerprint(pem)}', file=sys.stderr)


def cmd_fingerprint(args):
    print(keys.fingerprint(Path(args.file).read_bytes()))


def cmd_plans(args):
    plans = _plans(args)
    if args.json:
        print(json.dumps({s: p.__dict__ for s, p in plans.items()}, indent=2,
                         ensure_ascii=False))
        return
    for p in plans.values():
        prices = 'sur devis' if p.on_quote else (
            f'{fcfa(p.price_monthly)}/mois, {fcfa(p.price_yearly)}/an'
        )
        print(f'{p.slug}  -  {p.name}')
        print(f'    {prices} ; installation {fcfa(p.setup_fee)}')
        print(f'    {_limit(p.max_users if p.max_users < 100_000 else 0)} utilisateur(s)'
              f' (+{fcfa(p.extra_user_price)}/mois par utilisateur supplémentaire),'
              f' {_limit(p.max_clinics if p.max_clinics < 100_000 else 0)} clinique(s)')
        print('    ' + ', '.join(FEATURE_LABELS[f] for f in FEATURES if p.features[f]))


def cmd_quote(args):
    plan = _plan(args, args.plan)
    if plan.on_quote:
        print('Plan sur devis : pas de prix catalogue, fixer le montant négocié.')
    d = calculate_price(plan, args.cycle, args.extra_users, args.discount,
                        not args.no_setup)
    print(f'{plan.name} - {CYCLE_LABELS[args.cycle]}')
    print(f'  Base                     : {fcfa(d["base_price"])}')
    print(f'  Utilisateurs supp. ({args.extra_users})  : {fcfa(d["extra_users_price"])}')
    if d['discount']:
        print(f'  Remise ({d["discount_percent"]:g} %)        : -{fcfa(d["discount"])}')
    print(f'  Installation             : {fcfa(d["setup_fee"])}')
    print(f'  TOTAL                    : {fcfa(d["total"])}')


def _request(args, plan, cycle, starts, licensee, machine_id, **extra):
    return IssueRequest(
        licensee=licensee,
        plan=plan,
        cycle=cycle,
        starts=starts,
        licence_id=_register(args).next_id(),
        machine_id=machine_id,
        **extra,
    )


def cmd_issue(args):
    plan = _plan(args, args.plan)
    starts = args.start or date.today()
    req = _request(args, plan, args.cycle, starts, args.licensee, args.machine_id,
                   extra_users=args.extra_users, clinics=args.clinics,
                   enable=tuple(args.enable), disable=tuple(args.disable),
                   grace_days=args.grace_days)
    try:
        payload = build_payload(req)
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    if payload['expires'] and date.fromisoformat(payload['expires']) < date.today():
        raise CliError('Cette licence serait déjà expirée (vérifier --start).')
    _emit(args, payload)


def cmd_trial(args):
    plan = _plan(args, args.plan)
    req = _request(args, plan, 'trial', date.today(), args.licensee, args.machine_id,
                   trial_days=args.days)
    _emit(args, build_payload(req))


def _from_entry(args, licence_id):
    try:
        entry = _register(args).get(licence_id)
    except KeyError as exc:
        raise CliError(str(exc)) from exc
    old = payload_of(entry)
    if old.get('v') != 2:
        raise CliError('Licence v1 : réémettre avec « issue » en choisissant un plan.')
    return old


def cmd_renew(args):
    old = _from_entry(args, args.id)
    cycle = args.cycle or old['cycle']
    if cycle == 'trial':
        raise CliError('Un essai ne se renouvelle pas : préciser --cycle (mensuel, annuel...).')
    if old['expires'] is None:
        raise CliError('Licence perpétuelle : aucun renouvellement nécessaire.')
    # Enchaîne sans trou si l'ancienne période court encore, sinon repart d'aujourd'hui.
    previous_end = date.fromisoformat(old['expires'])
    starts = max(previous_end, date.today())
    plan = _plan(args, old['plan'])
    req = _request(args, plan, cycle, starts, old['licensee'], old['machine_id'],
                   clinics=old['limits']['clinics'],
                   grace_days=old['grace_days'] if old['cycle'] != 'trial' else None)
    payload = build_payload(req)
    # Les personnalisations (utilisateurs supp., modules) sont reconduites.
    payload['limits'] = dict(old['limits'])
    payload['features'] = dict(old['features'])
    _emit(args, payload, origin=f"renouvelle {old['id']}")


def cmd_upgrade(args):
    old = _from_entry(args, args.id)
    plan = _plan(args, args.plan)
    cycle = args.cycle or (old['cycle'] if old['cycle'] != 'trial' else 'yearly')
    req = _request(args, plan, cycle, args.start or date.today(), old['licensee'],
                   old['machine_id'], extra_users=args.extra_users)
    try:
        payload = build_payload(req)
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    _emit(args, payload, origin=f"remplace {old['id']}")


def cmd_verify(args):
    key = args.key
    if Path(key).is_file():
        key = Path(key).read_text(encoding='utf-8')
    if args.public_key:
        public = load_pem_public_key(Path(args.public_key).read_bytes())
    else:
        public = _private(args).public_key()
    result = verify(key, public, args.today)
    if result.payload:
        print(_describe(result.payload))
        if args.json:
            print(json.dumps(result.payload, indent=2, ensure_ascii=False))
    print(f'-> {result.message}')
    if not result.usable:
        sys.exit(1)


def cmd_list(args):
    today = date.today()
    soon = today + timedelta(days=args.expiring) if args.expiring is not None else None
    rows = []
    for e in _register(args).entries():
        if args.licensee and args.licensee.lower() not in e['titulaire'].lower():
            continue
        if args.plan and args.plan not in e['plan']:
            continue
        exp = e['expire']
        if soon is not None:
            try:
                d = date.fromisoformat(exp)
            except ValueError:
                continue
            if not today <= d <= soon:
                continue
        rows.append(e)
    for e in rows:
        print(f"{e['id']:<18} {e['titulaire'][:30]:<30} {e['plan']:<28} "
              f"{e['cycle']:<10} {e['expire']:<11} {e['poste'][:20]}")
    print(f'{len(rows)} licence(s).', file=sys.stderr)


def cmd_show(args):
    try:
        entry = _register(args).get(args.id)
    except KeyError as exc:
        raise CliError(str(exc)) from exc
    print(_describe(payload_of(entry)))
    if entry['origine']:
        print(f"Origine     : {entry['origine']}")
    print(f"\n{entry['cle']}")


# ─── analyse des arguments ───────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='vetotrace_license',
        description='Générateur de licences VétoTrace (application de bureau)',
    )
    parser.add_argument('--home', default=str(HOME),
                        help='dossier des clés et du registre (défaut : ~/.vetotrace)')
    parser.add_argument('--private-key', help='défaut : <home>/license_private.pem')
    sub = parser.add_subparsers(dest='cmd', required=True)

    k = sub.add_parser('keygen', help='créer la paire de clés (une seule fois)')
    k.add_argument('--public-out')
    k.add_argument('--encrypt', action='store_true',
                   help=f'chiffrer la clé privée par mot de passe ({keys.PASSWORD_ENV})')
    k.add_argument('--force', action='store_true')
    k.set_defaults(func=cmd_keygen)

    p = sub.add_parser('pubkey', help='exporter la clé publique')
    p.add_argument('--out')
    p.set_defaults(func=cmd_pubkey)

    f = sub.add_parser('fingerprint', help='empreinte d’une clé publique PEM')
    f.add_argument('file')
    f.set_defaults(func=cmd_fingerprint)

    pl = sub.add_parser('plans', help='catalogue des plans')
    pl.add_argument('--json', action='store_true')
    pl.set_defaults(func=cmd_plans)

    q = sub.add_parser('quote', help='prix d’une licence (FCFA)')
    q.add_argument('--plan', required=True)
    q.add_argument('--cycle', choices=CYCLES, default='yearly')
    q.add_argument('--extra-users', type=int, default=0)
    q.add_argument('--discount', type=float, default=0, help='remise en %%')
    q.add_argument('--no-setup', action='store_true', help='sans frais d’installation')
    q.set_defaults(func=cmd_quote)

    i = sub.add_parser('issue', help='émettre une licence')
    i.add_argument('--licensee', required=True, help='nom de la clinique titulaire')
    i.add_argument('--plan', required=True, help='slug (ex. vetotrace-solo ou solo)')
    i.add_argument('--cycle', choices=CYCLES, default='yearly')
    i.add_argument('--start', type=_date, help='AAAA-MM-JJ (défaut : aujourd’hui)')
    i.add_argument('--extra-users', type=int, default=0)
    i.add_argument('--clinics', type=int, help='nombre de cliniques (0 = illimité)')
    i.add_argument('--enable', action='append', default=[], choices=FEATURES,
                   help='activer un module hors plan (répétable)')
    i.add_argument('--disable', action='append', default=[], choices=FEATURES,
                   help='retirer un module du plan (répétable)')
    i.add_argument('--machine-id', help='identifiant affiché sur l’écran d’activation')
    i.add_argument('--grace-days', type=int,
                   help=f'jours de grâce après expiration (défaut {DEFAULT_GRACE_DAYS})')
    i.add_argument('--out', help='écrire aussi la clé dans ce fichier')
    i.set_defaults(func=cmd_issue)

    t = sub.add_parser('trial', help='émettre une licence d’essai')
    t.add_argument('--licensee', required=True)
    t.add_argument('--plan', default='vetotrace-petite-clinique')
    t.add_argument('--days', type=int, default=30)
    t.add_argument('--machine-id')
    t.add_argument('--out')
    t.set_defaults(func=cmd_trial)

    r = sub.add_parser('renew', help='renouveler une licence du registre')
    r.add_argument('id')
    r.add_argument('--cycle', choices=CYCLES)
    r.add_argument('--out')
    r.set_defaults(func=cmd_renew)

    u = sub.add_parser('upgrade', help='changer le plan d’une licence du registre')
    u.add_argument('id')
    u.add_argument('--plan', required=True)
    u.add_argument('--cycle', choices=CYCLES)
    u.add_argument('--start', type=_date)
    u.add_argument('--extra-users', type=int, default=0)
    u.add_argument('--out')
    u.set_defaults(func=cmd_upgrade)

    v = sub.add_parser('verify', help='vérifier une clé (texte ou fichier)')
    v.add_argument('key')
    v.add_argument('--public-key', help='vérifier avec une clé publique seule')
    v.add_argument('--today', type=_date, help=argparse.SUPPRESS)
    v.add_argument('--json', action='store_true')
    v.set_defaults(func=cmd_verify)

    ls = sub.add_parser('list', help='lister le registre')
    ls.add_argument('--licensee')
    ls.add_argument('--plan')
    ls.add_argument('--expiring', type=int, metavar='JOURS',
                    help='seulement celles qui expirent dans les N jours')
    ls.set_defaults(func=cmd_list)

    s = sub.add_parser('show', help='afficher une licence du registre')
    s.add_argument('id')
    s.set_defaults(func=cmd_show)
    return parser


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    args = build_parser().parse_args(argv)
    if not args.private_key:
        args.private_key = str(Path(args.home) / 'license_private.pem')
    try:
        args.func(args)
    except CliError as exc:
        print(f'Erreur : {exc}', file=sys.stderr)
        sys.exit(2)
