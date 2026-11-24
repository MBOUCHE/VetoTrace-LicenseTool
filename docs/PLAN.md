# Plan : générateur de licences VétoTrace (format v2, plans et quotas)

## 1. Constat (état au 2026-11-24)

| Élément | Existant |
|---|---|
| Outil éditeur | `vetotrace_license.py` : keygen / pubkey / issue / verify. La clé v1 porte uniquement `licensee`, `expires`, `machine_id`. |
| Application bureau | `veto_track_api/apps/desktop/license.py` vérifie la signature Ed25519 hors ligne, le poste, l'expiration et le recul d'horloge. |
| Plans SaaS | `apps/licensing/models.py::Plan` + `create_plan_fixtures` (7 plans : solo, petite clinique, moyenne, grande, entreprise, parapharmacie, public). Ils définissent des quotas (utilisateurs, cliniques, animaux, stockage) et 8 modules `has_*`. |
| Contrôle par plan | `module_required(flag)`, `check_user_quota`, `add_clinic_to_license`, `clinic_context.modules` : tous lisent `clinic.license.plan`. |

**Le problème** : sur le poste bureau, aucune `License` n'existe en base. Toute licence bureau
donne donc accès à **tout** (tous les modules, utilisateurs illimités). Impossible de vendre
une licence bureau « Solo » ou « Petite clinique ».

## 2. Objectifs

1. Une clé de licence **v2** qui porte le plan, le cycle, la période, les quotas et les modules.
2. Un outil éditeur complet : un catalogue des plans aligné sur `create_plan_fixtures`, l'émission
   par plan avec personnalisation (utilisateurs supplémentaires, modules en plus ou en moins), l'essai,
   le renouvellement, la mise à niveau, un registre interrogeable, le calcul du prix (FCFA) et une clé
   privée optionnellement chiffrée par mot de passe.
3. Une application bureau qui **applique** la licence v2 (modules, quota d'utilisateurs, nombre de
   cliniques, période de grâce) tout en acceptant les clés v1 déjà émises (accès complet, comme une
   clinique « legacy » sans licence en SaaS).

## 3. Format v2 (contrat outil ↔ application)

`<payload>.<signature>` en base64url sans padding. La signature Ed25519 porte sur les octets du payload JSON :

```json
{
  "v": 2,
  "id": "VT-20261124-0001",
  "licensee": "Clinique des Palmiers",
  "issued": "2026-11-24",
  "plan": "vetotrace-petite-clinique",
  "plan_name": "VétoTrace Petite Clinique",
  "edition": "small",
  "cycle": "yearly",
  "starts": "2026-11-24",
  "expires": "2027-11-24",
  "grace_days": 7,
  "machine_id": null,
  "limits": {"users": 7, "clinics": 1, "animals": 0, "storage_mb": 2000},
  "features": {"has_epidemiology": false, "has_lab_module": false, "...": true}
}
```

Règles :
- `cycle` ∈ `monthly | quarterly | yearly | lifetime | trial`. `lifetime` donne `expires = null`.
- `trial` : 30 jours par défaut, sans période de grâce.
- `limits.*` = `0` signifie illimité (même convention que `Plan.max_animals`).
- Les 8 clés de `features` sont exactement `UserSerializer._MODULE_FLAGS`.
- Une clé dont `starts` est dans le futur est refusée (« pas encore valide »).
- Entre `expires` et `expires + grace_days`, la clé reste valide avec `in_grace = true` (état analogue à `grace_period` en SaaS).
- L'application refuse tout `v` inconnu. Elle accepte `v = 1` avec un accès complet.

## 4. Outil éditeur (dépôt `VetoTrace-LicenseTool`)

Paquet `vetotrace_license/` (+ un `vetotrace_license.py` conservé comme point d'entrée) :

| Module | Rôle |
|---|---|
| `catalog.py` | Les 7 plans (quotas, modules, prix FCFA) alignés sur `create_plan_fixtures` ; un `plans.json` optionnel dans `~/.vetotrace/` les surcharge. |
| `dates.py` | `add_months` et `compute_end_date`, identiques à `licensing/services.py`. |
| `pricing.py` | Le prix, identique à `calculate_price` (base du cycle, utilisateurs supplémentaires × mois, remise %, frais d'installation). |
| `keys.py` | keygen (Ed25519, PEM PKCS8, chiffrement optionnel par mot de passe), chargement, export de la clé publique, empreinte. |
| `licence.py` | Construction et validation du payload, signature, décodage et vérification (v1 + v2). |
| `register.py` | Registre CSV (`licences_emises.csv`, séparateur `;`) migré depuis l'ancien format, avec un identifiant séquentiel. |
| `cli.py` | Les commandes. |

Commandes : `keygen`, `pubkey` (+ empreinte), `plans` (catalogue), `quote` (prix),
`issue` (plan, cycle, `--start`, `--extra-users`, `--clinics`, `--enable/--disable` module,
`--machine-id`, `--grace-days`, `--out`), `trial`, `renew <id>` (même titulaire, plan, poste et
options, période suivante), `upgrade <id> --plan`, `verify <clé|fichier>`, `list` (filtres).

Tests `pytest` : catalogue ↔ modules attendus, dates de fin, prix, aller-retour signature,
refus des falsifications, renouvellement et registre.

## 5. Application (dépôt `veto_track`)

- `apps/desktop/license.py` : `LicenseStatus` reçoit `plan`, `plan_name`, `cycle`, `limits`,
  `features`, `in_grace`, `license_id` et `version`. `verify_key` gère v1 et v2. L'entitlement courant
  est exposé (`current_entitlements()`, `None` hors bureau).
- `apps/licensing/permissions.py::module_required` : en mode bureau, une clinique sans licence en base
  lit le module dans la licence du poste.
- `apps/licensing/services.py::check_user_quota` : en mode bureau, sans licence en base, le quota =
  `limits.users` (0 = illimité).
- `apps/authentication/serializers.py::get_clinic_context` : en mode bureau, il reflète le plan de la
  licence du poste (nom du plan, modules) pour que le front masque les menus.
- `GET /api/v1/desktop/license/` renvoie le détail du plan (pour l'écran d'activation).
- Tests ajoutés dans `apps/desktop/tests/test_desktop.py`.

Hors SaaS, rien ne change : `current_entitlements()` renvoie `None` dès que `DESKTOP_LICENSE_FILE`
n'est pas défini dans les settings.

## 6. Hors périmètre

- La révocation en ligne : impossible hors ligne par construction. On passe par des licences courtes
  et des renouvellements.
- Le quota de stockage et d'animaux : il est transporté dans la clé, mais l'application ne l'applique pas
  aujourd'hui, en SaaS non plus. Ce sera un chantier séparé.
- Le frontend : l'écran d'activation peut afficher les nouveaux champs. C'est un lot ultérieur.
