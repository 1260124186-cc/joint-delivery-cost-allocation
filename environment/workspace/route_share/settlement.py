from fractions import Fraction
from math import gcd


def validate_instance(instance):
    return None


def validate_shares(payload):
    return None


def settle_shares(instance, payload):
    settlement = {}
    for share in payload["shares"]:
        value = share["numerator"] / share["denominator"]
        settlement[share["order_id"]] = int(value + 0.5)
    total = sum(settlement.values())
    return {
        "settlement_cents": dict(sorted(settlement.items())),
        "allocated_total_cents": total,
        "rounding_remainder_cents": payload["total_cost_cents"] - total,
    }
