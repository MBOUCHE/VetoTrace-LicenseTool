"""Catalogue des plans VétoTrace.

Reproduction à l'identique de
`veto_track_api/apps/licensing/management/commands/create_plan_fixtures.py`
(slugs, quotas, modules, prix FCFA). Toute évolution des plans côté
application doit être répercutée ici (ou via `~/.vetotrace/plans.json`).

Dans la clé de licence, un quota à 0 signifie « illimité » (même convention
que `Plan.max_animals`) ; l'`UNLIMITED = 100_000` des fixtures devient donc 0.
"""

import json
from dataclasses import dataclass, field, fields
from pathlib import Path

UNLIMITED = 100_000

# Ordre et noms identiques à `UserSerializer._MODULE_FLAGS`.
FEATURES = (
    'has_epidemiology',
    'has_lab_module',
    'has_hospitalization',
    'has_api_access',
    'has_whatsapp_notif',
    'has_export_excel',
    'has_multi_clinic',
    'has_priority_support',
)

FEATURE_LABELS = {
    'has_epidemiology': 'Épidémiologie',
    'has_lab_module': 'Laboratoire',
    'has_hospitalization': 'Hospitalisation',
    'has_api_access': 'Accès API',
    'has_whatsapp_notif': 'Notifications WhatsApp',
    'has_export_excel': 'Exports Excel',
    'has_multi_clinic': 'Multi-cliniques',
    'has_priority_support': 'Support prioritaire',
}

CYCLES = ('monthly', 'quarterly', 'yearly', 'lifetime')
CYCLE_LABELS = {
    'monthly': 'Mensuel',
    'quarterly': 'Trimestriel',
    'yearly': 'Annuel',
    'lifetime': 'Perpétuelle',
    'trial': 'Essai',
}


@dataclass(frozen=True)
class Plan:
    slug: str
    name: str
    structure_type: str
    price_monthly: int
    price_quarterly: int
    price_yearly: int
    price_lifetime: int
    setup_fee: int
    max_users: int
    extra_user_price: int
    max_clinics: int
    max_animals: int
    max_storage_mb: int
    features: dict = field(default_factory=dict)

    def price_for_cycle(self, cycle: str) -> int:
        return {
            'monthly': self.price_monthly,
            'quarterly': self.price_quarterly,
            'yearly': self.price_yearly,
            'lifetime': self.price_lifetime,
        }.get(cycle, self.price_monthly)

    @property
    def on_quote(self) -> bool:
        """Tarification sur devis (aucun prix catalogue)."""
        return not any(
            (self.price_monthly, self.price_quarterly, self.price_yearly)
        )


def _plan(slug, name, structure_type, prices, setup_fee, max_users, extra_user_price,
          max_clinics, max_storage_mb, enabled):
    monthly, quarterly, yearly = prices
    return Plan(
        slug=slug,
        name=name,
        structure_type=structure_type,
        price_monthly=monthly,
        price_quarterly=quarterly,
        price_yearly=yearly,
        price_lifetime=0,
        setup_fee=setup_fee,
        max_users=max_users,
        extra_user_price=extra_user_price,
        max_clinics=max_clinics,
        max_animals=0,
        max_storage_mb=max_storage_mb,
        features={f: f in enabled for f in FEATURES},
    )


_ALL = set(FEATURES)

DEFAULT_PLANS = (
    _plan('vetotrace-solo', 'VétoTrace Solo', 'solo',
          (15_000, 42_000, 150_000), 20_000, 1, 8_000, 1, 500,
          {'has_hospitalization', 'has_export_excel'}),
    _plan('vetotrace-petite-clinique', 'VétoTrace Petite Clinique', 'small',
          (35_000, 99_000, 360_000), 30_000, 5, 7_000, 1, 2_000,
          {'has_hospitalization', 'has_whatsapp_notif', 'has_export_excel'}),
    _plan('vetotrace-clinique-moyenne', 'VétoTrace Clinique Moyenne', 'medium',
          (75_000, 213_000, 780_000), 50_000, 15, 6_000, 1, 10_000,
          {'has_epidemiology', 'has_lab_module', 'has_hospitalization',
           'has_whatsapp_notif', 'has_export_excel'}),
    _plan('vetotrace-grande-clinique', 'VétoTrace Grande Clinique', 'large',
          (150_000, 426_000, 1_500_000), 100_000, 50, 5_000, 1, 50_000,
          _ALL - {'has_multi_clinic'}),
    _plan('vetotrace-entreprise', 'VétoTrace Entreprise', 'enterprise',
          (0, 0, 0), 0, UNLIMITED, 0, UNLIMITED, 0, _ALL),
    _plan('vetotrace-parapharmacie', 'VétoTrace Parapharmacie', 'parapharmacie',
          (20_000, 57_000, 200_000), 25_000, 3, 7_000, 1, 1_000,
          {'has_whatsapp_notif', 'has_export_excel'}),
    _plan('vetotrace-public', 'VétoTrace Public', 'public',
          (50_000, 142_000, 500_000), 0, 20, 4_000, 1, 20_000,
          _ALL - {'has_multi_clinic', 'has_whatsapp_notif'}),
)


def load_plans(override: Path | None = None) -> dict[str, Plan]:
    """Plans par slug ; `override` (JSON, liste d'objets Plan) remplace ou
    ajoute des plans par slug."""
    plans = {p.slug: p for p in DEFAULT_PLANS}
    if override and override.exists():
        allowed = {f.name for f in fields(Plan)}
        for raw in json.loads(override.read_text(encoding='utf-8')):
            base = plans.get(raw.get('slug'))
            data = {f.name: getattr(base, f.name) for f in fields(Plan)} if base else {}
            data.update({k: v for k, v in raw.items() if k in allowed})
            feats = {f: False for f in FEATURES}
            feats.update(data.get('features') or {})
            data['features'] = {f: bool(feats[f]) for f in FEATURES}
            plans[data['slug']] = Plan(**data)
    return plans


def limit(value: int) -> int:
    """Quota du catalogue → quota de la clé (UNLIMITED → 0)."""
    return 0 if value >= UNLIMITED else int(value)
