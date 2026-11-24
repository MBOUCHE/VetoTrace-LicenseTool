"""Registre des licences émises (CSV `;`, ouvrable dans Excel).

L'ancien registre (colonnes `emise_le;titulaire;expire;poste;cle`) est migré
automatiquement à la première écriture/lecture : une copie `.v1.bak` est
conservée, aucune ligne n'est perdue.
"""

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

COLUMNS = [
    'id', 'emise_le', 'titulaire', 'plan', 'cycle', 'debut', 'expire', 'poste',
    'utilisateurs', 'cliniques', 'modules', 'origine', 'cle',
]
LEGACY_COLUMNS = ['emise_le', 'titulaire', 'expire', 'poste', 'cle']


@dataclass
class Entry:
    row: dict

    def __getitem__(self, item):
        return self.row.get(item, '')


class Register:
    def __init__(self, path: Path):
        self.path = path

    # ─── lecture ─────────────────────────────────────────────────────────
    def _read_raw(self) -> tuple[list[str], list[dict]]:
        if not self.path.exists():
            return COLUMNS, []
        with self.path.open(newline='', encoding='utf-8') as fh:
            reader = csv.DictReader(fh, delimiter=';')
            return list(reader.fieldnames or []), list(reader)

    def migrate(self) -> int:
        """Convertit un registre v1 ; renvoie le nombre de lignes migrées."""
        if not self.path.exists():
            return 0
        header, rows = self._read_raw()
        if header == COLUMNS:
            return 0
        if header != LEGACY_COLUMNS:
            raise ValueError(f'Registre au format inconnu : {self.path}')
        shutil.copy2(self.path, self.path.with_suffix('.v1.bak'))
        migrated = []
        for n, row in enumerate(rows, 1):
            migrated.append({
                'id': f'V1-{n:04d}',
                'emise_le': row['emise_le'],
                'titulaire': row['titulaire'],
                'plan': 'v1 (accès complet)',
                'cycle': '',
                'debut': '',
                'expire': row['expire'],
                'poste': row['poste'],
                'utilisateurs': 'illimité',
                'cliniques': '',
                'modules': 'tous',
                'origine': '',
                'cle': row['cle'],
            })
        self._write_all(migrated)
        return len(migrated)

    def entries(self) -> list[Entry]:
        self.migrate()
        return [Entry(r) for r in self._read_raw()[1]]

    def get(self, licence_id: str) -> Entry:
        for e in self.entries():
            if e['id'] == licence_id:
                return e
        raise KeyError(f'Licence {licence_id} absente du registre.')

    def next_id(self, today: date | None = None) -> str:
        prefix = f'VT-{(today or date.today()):%Y%m%d}-'
        used = [int(e['id'][len(prefix):]) for e in self.entries()
                if e['id'].startswith(prefix) and e['id'][len(prefix):].isdigit()]
        return f'{prefix}{max(used, default=0) + 1:04d}'

    # ─── écriture ────────────────────────────────────────────────────────
    def _write_all(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        with tmp.open('w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
        tmp.replace(self.path)

    def add(self, payload: dict, key: str, origin: str = '') -> None:
        self.migrate()
        new_file = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter=';')
            if new_file:
                writer.writeheader()
            limits = payload['limits']
            writer.writerow({
                'id': payload['id'],
                'emise_le': datetime.now().isoformat(timespec='seconds'),
                'titulaire': payload['licensee'],
                'plan': payload['plan'],
                'cycle': payload['cycle'],
                'debut': payload['starts'],
                'expire': payload['expires'] or 'illimitée',
                'poste': payload['machine_id'] or 'tout poste',
                'utilisateurs': limits['users'] or 'illimité',
                'cliniques': limits['clinics'] or 'illimité',
                'modules': ','.join(f for f, on in payload['features'].items() if on),
                'origine': origin,
                'cle': key,
            })


def payload_of(entry: Entry) -> dict:
    """Payload décodé d'une entrée du registre (sans vérifier la signature)."""
    from .licence import unb64

    return json.loads(unb64(entry['cle'].split('.')[0]))
