from fractions import Fraction
from math import factorial


def _cost_table(instance, payload):
    order_ids = sorted(stop["id"] for stop in instance["stops"])
    known = set(order_ids)
    expected = {
        frozenset(members)
        for size in range(1, len(order_ids) + 1)
        for members in __import__("itertools").combinations(order_ids, size)
    }
    rows = payload.get("coalitions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("coalitions must be a list")
    costs = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("coalition row must be an object")
        members = row.get("members")
        cost = row.get("cost_cents")
        if (
            not isinstance(members, list)
            or not members
            or not all(isinstance(member, str) and member for member in members)
            or members != sorted(members)
            or len(set(members)) != len(members)
            or not set(members) <= known
        ):
            raise ValueError("invalid coalition members")
        if isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
            raise ValueError("coalition cost must be a nonnegative integer")
        key = frozenset(members)
        if key in costs:
            raise ValueError("duplicate coalition")
        costs[key] = cost
    if set(costs) != expected:
        raise ValueError("coalition file is incomplete")
    return order_ids, costs


def build_shares(instance, payload):
    order_ids, costs = _cost_table(instance, payload)
    count = len(order_ids)
    denominator = factorial(count)
    shares = []
    for index, order_id in enumerate(order_ids):
        value = Fraction(0)
        for mask in range(1 << count):
            if mask & (1 << index):
                continue
            subset = frozenset(
                order_ids[position]
                for position in range(count)
                if mask & (1 << position)
            )
            larger = subset | {order_id}
            weight = Fraction(
                factorial(len(subset)) * factorial(count - len(subset) - 1),
                denominator,
            )
            value += weight * (costs[larger] - costs[subset])
        shares.append(
            {
                "order_id": order_id,
                "numerator": value.numerator,
                "denominator": value.denominator,
            }
        )
    return {
        "shares": shares,
        "total_cost_cents": costs[frozenset(order_ids)],
        "efficiency_holds": True,
    }
