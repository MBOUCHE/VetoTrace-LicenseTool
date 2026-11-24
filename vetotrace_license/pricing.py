"""Prix d'une licence en FCFA : même logique que `calculate_price`
(`apps/licensing/services.py`)."""

from decimal import ROUND_HALF_EVEN, Decimal

from .catalog import Plan

CYCLE_MULTIPLIER = {'monthly': 1, 'quarterly': 3, 'yearly': 12, 'lifetime': 12}


def calculate_price(plan: Plan, cycle: str, extra_users: int = 0,
                    discount_percent: float = 0, include_setup: bool = True) -> dict:
    base = Decimal(plan.price_for_cycle(cycle) or 0)
    extra = (Decimal(extra_users) * Decimal(plan.extra_user_price or 0)
             * CYCLE_MULTIPLIER.get(cycle, 1))
    setup = Decimal(plan.setup_fee or 0) if include_setup else Decimal(0)
    pct = Decimal(str(discount_percent))
    discount = ((base + extra) * pct / Decimal(100)).quantize(
        Decimal('1'), rounding=ROUND_HALF_EVEN
    )
    return {
        'base_price': int(base),
        'extra_users_price': int(extra),
        'setup_fee': int(setup),
        'discount_percent': float(pct),
        'discount': int(discount),
        'total': int(base + extra - discount + setup),
    }


def fcfa(amount: int) -> str:
    return f'{amount:,}'.replace(',', ' ') + ' FCFA'
