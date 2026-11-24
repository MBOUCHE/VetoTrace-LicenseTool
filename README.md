# VétoTrace : générateur de licences (outil éditeur)

Outil interne, **hors du dépôt applicatif**. Il signe les licences de l'application de bureau
avec une clé privée Ed25519. L'application, elle, n'embarque que la clé publique : elle peut
vérifier une licence hors ligne, mais pas en fabriquer une.

## Installation
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Utilisation
| Besoin | Commande |
|---|---|
| Créer la paire de clés (une seule fois) | `python vetotrace_license.py keygen` |
| Émettre une licence liée à un poste | `python vetotrace_license.py issue --licensee "Clinique X" --expires 2027-12-31 --machine-id <id>` |
| Émettre une licence valable sur tout poste, sans expiration | `python vetotrace_license.py issue --licensee "Clinique X"` |
| Vérifier une licence (support client) | `python vetotrace_license.py verify <clé>` |
| Réexporter la clé publique | `python vetotrace_license.py pubkey --out license_public_key.pem` |

L'identifiant de poste (`--machine-id`) s'affiche sur l'écran d'activation de l'application.

## Fichiers (dans `%USERPROFILE%\.vetotrace\`)
- `license_private.pem` : **secret**. Sauvegardez-le hors ligne : sans lui, plus aucune
  licence ne peut être émise. S'il fuit, n'importe qui peut en fabriquer.
- `license_public_key.pem` : à copier dans
  `veto_track_api/apps/desktop/license_public_key.pem` avant de compiler l'application.
- `licences_emises.csv` : registre de toutes les licences émises.

Régénérer les clés (`keygen --force`) invalide **toutes** les licences déjà émises.
