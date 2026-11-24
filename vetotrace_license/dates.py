"""Calcul des périodes : même logique que `apps/licensing/services.py`."""

from datetime import date, timedelta

CYCLE_MONTHS = {'monthly': 1, 'quarterly': 3, 'yearly': 12, 'lifetime': None}
TRIAL_DAYS = 30


def add_months(start: date, months: int) -> date:
    """Ajoute `months` mois en ramenant le jour à la fin du mois si besoin."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(start.day, last_day))


def compute_end_date(start: date, cycle: str, trial_days: int = TRIAL_DAYS):
    """Date de fin de période (None si perpétuelle)."""
    if cycle == 'trial':
        return start + timedelta(days=trial_days)
    if cycle not in CYCLE_MONTHS:
        raise ValueError(f'Cycle inconnu : {cycle}')
    months = CYCLE_MONTHS[cycle]
    return None if months is None else add_months(start, months)
