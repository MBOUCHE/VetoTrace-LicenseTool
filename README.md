# VétoTrace : générateur de licences (outil éditeur)

Cet outil est interne à l'éditeur et reste **hors du dépôt applicatif**. Il signe avec une clé
privée Ed25519 les licences de l'application de bureau VétoTrace. L'application n'embarque que
la clé publique : elle vérifie une licence hors ligne, mais ne peut pas en fabriquer.

Depuis la v2, une licence porte **le plan** (Solo, Petite clinique, Moyenne, Grande, Entreprise,
Parapharmacie, Public), le cycle, la période, les quotas (utilisateurs, cliniques) et les
modules. L'application les applique. Les clés v1 déjà émises restent valides et donnent
un accès complet.
Conception : [docs/PLAN.md](docs/PLAN.md). Prompt d'implémentation : [docs/PROMPT.md](docs/PROMPT.md).

## Installation
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
```

## Utilisation
`python vetotrace_license.py <commande>` (ou `python -m vetotrace_license <commande>`).

| Besoin | Commande |
|---|---|
| Créer la paire de clés (une seule fois), avec la clé privée chiffrée | `keygen --encrypt` |
| Voir le catalogue des plans | `plans` |
| Chiffrer une offre (FCFA) | `quote --plan petite-clinique --cycle yearly --extra-users 2 --discount 10` |
| Émettre une licence annuelle | `issue --licensee "Clinique X" --plan petite-clinique` |
| … liée à un poste, avec des options | `issue --licensee "Clinique X" --plan solo --extra-users 1 --enable has_lab_module --machine-id <id>` |
| … multi-sites | `issue --licensee "Groupe Y" --plan entreprise --clinics 4` |
| … perpétuelle | `issue --licensee "Clinique X" --plan solo --cycle lifetime` |
| Émettre un essai (30 jours par défaut) | `trial --licensee "Clinique X" --plan clinique-moyenne` |
| Renouveler (période suivante, mêmes options) | `renew VT-20261124-0001` |
| Changer de plan | `upgrade VT-20261124-0001 --plan grande-clinique` |
| Vérifier une clé (support client) | `verify <clé ou fichier>` (`--public-key` pour vérifier sans la clé privée) |
| Consulter le registre | `list`, `list --expiring 30`, `show VT-20261124-0001` |
| Contrôler la clé publique embarquée | `fingerprint chemin\license_public_key.pem` |

L'identifiant de poste (`--machine-id`) s'affiche sur l'écran d'activation de l'application.
Les modules (`--enable` / `--disable`) sont : `has_epidemiology`, `has_lab_module`,
`has_hospitalization`, `has_api_access`, `has_whatsapp_notif`, `has_export_excel`,
`has_multi_clinic`, `has_priority_support`.

Si la clé privée est chiffrée, l'outil demande le mot de passe. Vous pouvez aussi le fournir dans
la variable `VETOTRACE_KEY_PASSWORD`.

## Règles appliquées par l'application
- Hors de sa période (`starts` → `expires`), la licence est refusée. Après l'expiration, elle reste
  valide pendant la période de grâce (7 jours par défaut, aucune pour un essai ou une licence
  perpétuelle).
- Un module absent de la licence est refusé par l'API et masqué dans le menu.
- Le quota d'utilisateurs s'applique à tout le poste. Un quota à `0` signifie illimité.
- Le nombre de cliniques est plafonné par `limits.clinics`.
- Une licence émise ne peut pas être révoquée à distance : le poste est hors ligne. Préférez des
  cycles courts et utilisez `renew`.

## Fichiers (dans `%USERPROFILE%\.vetotrace\`, modifiable avec `--home`)
- `license_private.pem` : **secret**. Sauvegardez-le hors ligne : sans lui, plus aucune
  licence ne peut être émise. S'il fuit, n'importe qui peut en fabriquer.
- `license_public_key.pem` : à copier dans
  `veto_track_api/apps/desktop/license_public_key.pem` avant de compiler l'application.
- `licences_emises.csv` : le registre de toutes les licences émises. L'ancien format est migré
  automatiquement et une sauvegarde `.v1.bak` est conservée.
- `plans.json` (facultatif) : surcharge le catalogue si les plans de l'application évoluent.
  Par défaut, le catalogue reprend `create_plan_fixtures`.

Régénérer les clés (`keygen --force`) invalide **toutes** les licences déjà émises.

## Tests
```
python -m pytest
```
