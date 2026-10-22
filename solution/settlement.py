import math
from fractions import Fraction


def _is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_instance(instance):
    if not isinstance(instance, dict):
        raise ValueError("instance must be an object")
    instance_id = instance.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id.strip():
        raise ValueError("instance_id must be a nonempty string")
    depot = instance.get("depot")
    stops = instance.get("stops")
    if not isinstance(depot, dict):
        raise ValueError("depot must be an object")
    if not isinstance(stops, list) or not 1 <= len(stops) <= 10:
        raise ValueError("stops must contain between one and ten orders")
    nodes = [depot] + stops
    identifiers = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("each node must be an object")
        identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("each node needs a nonempty id")
        for key in ("x_m", "y_m"):
            if not _is_integer(node.get(key)):
                raise ValueError(f"{key} must be an integer")
        if node is not depot:
            maximum = node.get("max_settlement_cents")
            if not _is_integer(maximum) or maximum < 0:
                raise ValueError("max_settlement_cents must be a nonnegative integer")
        identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("node ids must be unique")
    factor = instance.get("road_factor")
    if (
        isinstance(factor, bool)
        or not isinstance(factor, (int, float))
        or not math.isfinite(factor)
        or factor <= 0
    ):
        raise ValueError("road_factor must be positive")
    rate = instance.get("rate_cents_per_km")
    if not _is_integer(rate) or rate <= 0:
        raise ValueError("rate_cents_per_km must be a positive integer")
    fee = instance.get("dispatch_fee_cents")
    if not _is_integer(fee) or fee < 0:
        raise ValueError("dispatch_fee_cents must be a nonnegative integer")


def validate_shares(payload):
    if not isinstance(payload, dict):
        raise ValueError("shares must be an object")
    total = payload.get("total_cost_cents")
    if not _is_integer(total) or total < 0:
        raise ValueError("total_cost_cents must be a nonnegative integer")
    if payload.get("efficiency_holds") is not True:
        raise ValueError("efficiency_holds must be true")
    rows = payload.get("shares")
    if not isinstance(rows, list) or not rows:
        raise ValueError("shares must be a nonempty list")
    seen = set()
    exact_sum = Fraction(0)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("share row must be an object")
        identifier = row.get("order_id")
        numerator = row.get("numerator")
        denominator = row.get("denominator")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("share ids must be unique nonempty strings")
        if not _is_integer(numerator) or not _is_integer(denominator):
            raise ValueError("share terms must be integers")
        if numerator < 0 or denominator <= 0:
            raise ValueError("share must be nonnegative with a positive denominator")
        if math.gcd(abs(numerator), denominator) != 1:
            raise ValueError("share fraction must be reduced")
        seen.add(identifier)
        exact_sum += Fraction(numerator, denominator)
    if exact_sum != total:
        raise ValueError("exact shares must sum to total_cost_cents")


def settle_shares(instance, payload):
    validate_instance(instance)
    validate_shares(payload)
    exact = {}
    for row in payload["shares"]:
        exact[row["order_id"]] = Fraction(row["numerator"], row["denominator"])
    order_ids = sorted(stop["id"] for stop in instance["stops"])
    if set(order_ids) != set(exact):
        raise ValueError("share ids must match instance stops")
    caps = {
        stop["id"]: stop["max_settlement_cents"]
        for stop in instance["stops"]
    }
    if sum(caps.values()) < payload["total_cost_cents"]:
        raise ValueError("settlement caps cannot cover total_cost_cents")

    marginals = []
    for index, identifier in enumerate(order_ids):
        upper = min(caps[identifier], payload["total_cost_cents"])
        for amount in range(1, upper + 1):
            marginal = Fraction(2 * amount - 1) - 2 * exact[identifier]
            marginals.append((marginal, -index, identifier))
    marginals.sort()
    settlement = {identifier: 0 for identifier in order_ids}
    for _marginal, _index, identifier in marginals[: payload["total_cost_cents"]]:
        settlement[identifier] += 1
    allocated = sum(settlement.values())
    return {
        "settlement_cents": settlement,
        "allocated_total_cents": allocated,
        "rounding_remainder_cents": payload["total_cost_cents"] - allocated,
    }
