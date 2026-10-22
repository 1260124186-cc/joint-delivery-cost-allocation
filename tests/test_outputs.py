"""Independent checks for exact shared-delivery cost allocation."""

import json
import os
import random
import subprocess
import sys
import tempfile
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
from itertools import combinations, permutations
from math import factorial
from pathlib import Path


WORKSPACE = Path("/workspace")
CANDIDATE_ENTRY = os.environ.get("TASK_ENTRY", "/workspace/route_share/__main__.py")
COMMAND = [sys.executable, "-m", "route_share"]
COMPARE_QUANTUM = Decimal("0.000000000000000001")


def make_instance(identifiers, coordinates, factor=1.18, rate=268, fee=9800, caps=None):
    """Build a valid instance with a depot at the origin."""
    caps = caps or {identifier: 1000000 for identifier in identifiers}
    return {
        "instance_id": "test-" + "-".join(identifiers),
        "depot": {"id": "D", "x_m": 0, "y_m": 0},
        "stops": [
            {
                "id": identifier,
                "x_m": point[0],
                "y_m": point[1],
                "max_settlement_cents": caps[identifier],
            }
            for identifier, point in zip(identifiers, coordinates, strict=True)
        ],
        "road_factor": factor,
        "rate_cents_per_km": rate,
        "dispatch_fee_cents": fee,
    }


def invoke(stage, inputs, existing=None):
    """Run one CLI stage and return its exit status, raw text, and stderr."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        paths = []
        for index, payload in enumerate(inputs):
            path = root / f"input-{index}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            paths.append(str(path))
        output = root / "output.json"
        if existing is not None:
            output.write_text(existing, encoding="utf-8")
        completed = subprocess.run(
            COMMAND + [stage] + paths + [str(output)],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=30,
        )
        raw = output.read_text(encoding="utf-8") if output.exists() else None
        return completed.returncode, raw, completed.stderr


def run_json(stage, inputs):
    """Run one stage and parse a successful JSON result."""
    status, raw, _stderr = invoke(stage, inputs)
    if status != 0 or raw is None:
        return None
    return json.loads(raw)


def route_reference(instance):
    """Enumerate every tour and independently rebuild all coalition costs."""
    positions = {
        instance["depot"]["id"]: (
            Decimal(instance["depot"]["x_m"]),
            Decimal(instance["depot"]["y_m"]),
        )
    }
    for stop in instance["stops"]:
        positions[stop["id"]] = (Decimal(stop["x_m"]), Decimal(stop["y_m"]))
    with localcontext() as context:
        context.prec = 50
        matrix = {}
        for left, (x1, y1) in positions.items():
            for right, (x2, y2) in positions.items():
                if left != right:
                    matrix[(left, right)] = ((x2 - x1) ** 2 + (y2 - y1) ** 2).sqrt()
        depot = instance["depot"]["id"]
        order_ids = sorted(stop["id"] for stop in instance["stops"])
        rows = []
        for size in range(1, len(order_ids) + 1):
            for members in combinations(order_ids, size):
                candidates = []
                for order in permutations(members):
                    route = (depot,) + order + (depot,)
                    distance = sum(
                        (
                            matrix[(route[index], route[index + 1])]
                            for index in range(len(route) - 1)
                        ),
                        Decimal(0),
                    ).quantize(COMPARE_QUANTUM, rounding=ROUND_HALF_UP)
                    candidates.append((distance, order))
                distance, order = min(candidates)
                raw_cents = (
                    distance
                    * Decimal(str(instance["road_factor"]))
                    * Decimal(instance["rate_cents_per_km"])
                    / Decimal(1000)
                )
                cost = instance["dispatch_fee_cents"] + int(
                    raw_cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
                rows.append(
                    {
                        "members": list(members),
                        "cost_cents": cost,
                        "tour": [depot] + list(order) + [depot],
                    }
                )
    return rows


def route_reference_dp(instance):
    """Compute all coalition routes with exact subset dynamic programming."""
    positions = {
        instance["depot"]["id"]: (
            Decimal(instance["depot"]["x_m"]),
            Decimal(instance["depot"]["y_m"]),
        )
    }
    for stop in instance["stops"]:
        positions[stop["id"]] = (Decimal(stop["x_m"]), Decimal(stop["y_m"]))
    depot = instance["depot"]["id"]
    order_ids = sorted(stop["id"] for stop in instance["stops"])
    count = len(order_ids)
    with localcontext() as context:
        context.prec = 50
        matrix = {}
        for left, (x1, y1) in positions.items():
            for right, (x2, y2) in positions.items():
                if left != right:
                    matrix[(left, right)] = ((x2 - x1) ** 2 + (y2 - y1) ** 2).sqrt()
        states = {
            (1 << index, index): (
                matrix[(depot, identifier)],
                (index,),
            )
            for index, identifier in enumerate(order_ids)
        }
        for mask in range(1, 1 << count):
            for last in range(count):
                current = states.get((mask, last))
                if current is None:
                    continue
                for following in range(count):
                    if mask & (1 << following):
                        continue
                    next_mask = mask | (1 << following)
                    candidate = (
                        current[0] + matrix[(order_ids[last], order_ids[following])],
                        current[1] + (following,),
                    )
                    known = states.get((next_mask, following))
                    if known is None or candidate < known:
                        states[(next_mask, following)] = candidate
        rows = []
        for size in range(1, count + 1):
            for members in combinations(order_ids, size):
                mask = sum(1 << order_ids.index(member) for member in members)
                choices = []
                for last in range(count):
                    if not (mask & (1 << last)):
                        continue
                    distance = states[(mask, last)][0] + matrix[(order_ids[last], depot)]
                    choices.append(
                        (
                            distance.quantize(COMPARE_QUANTUM, rounding=ROUND_HALF_UP),
                            states[(mask, last)][1],
                        )
                    )
                distance, path = min(choices)
                raw_cents = (
                    distance
                    * Decimal(str(instance["road_factor"]))
                    * Decimal(instance["rate_cents_per_km"])
                    / Decimal(1000)
                )
                cost = instance["dispatch_fee_cents"] + int(
                    raw_cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
                rows.append(
                    {
                        "members": list(members),
                        "cost_cents": cost,
                        "tour": [depot] + [order_ids[index] for index in path] + [depot],
                    }
                )
    return rows


def coalition_payload(instance, cost_function):
    """Build a complete coalition file from an arbitrary integer value function."""
    order_ids = sorted(stop["id"] for stop in instance["stops"])
    rows = []
    for size in range(1, len(order_ids) + 1):
        for members in combinations(order_ids, size):
            rows.append(
                {
                    "members": list(members),
                    "cost_cents": cost_function(members),
                    "tour": [instance["depot"]["id"]] + list(members) + [instance["depot"]["id"]],
                }
            )
    return {"instance_id": instance["instance_id"], "coalitions": rows}


def shapley_reference(instance, coalition_file):
    """Compute exact Shapley shares from the supplied coalition values."""
    order_ids = sorted(stop["id"] for stop in instance["stops"])
    costs = {frozenset(row["members"]): row["cost_cents"] for row in coalition_file["coalitions"]}
    costs[frozenset()] = 0
    count = len(order_ids)
    shares = []
    for index, identifier in enumerate(order_ids):
        value = Fraction(0)
        for mask in range(1 << count):
            if mask & (1 << index):
                continue
            subset = frozenset(
                order_ids[position]
                for position in range(count)
                if mask & (1 << position)
            )
            weight = Fraction(
                factorial(len(subset)) * factorial(count - len(subset) - 1),
                factorial(count),
            )
            value += weight * (costs[subset | {identifier}] - costs[subset])
        shares.append(
            {
                "order_id": identifier,
                "numerator": value.numerator,
                "denominator": value.denominator,
            }
        )
    return {
        "shares": shares,
        "total_cost_cents": costs[frozenset(order_ids)],
        "efficiency_holds": True,
    }


def share_payload(total, values):
    """Build an exact shares file for settlement tests."""
    rows = []
    for identifier, fraction in sorted(values.items()):
        rows.append(
            {
                "order_id": identifier,
                "numerator": fraction.numerator,
                "denominator": fraction.denominator,
            }
        )
    return {"shares": rows, "total_cost_cents": total, "efficiency_holds": True}


def settlement_reference(payload, instance):
    """Solve the bounded squared-error integer allocation by marginal costs."""
    exact = {
        row["order_id"]: Fraction(row["numerator"], row["denominator"])
        for row in payload["shares"]
    }
    order_ids = sorted(stop["id"] for stop in instance["stops"])
    caps = {stop["id"]: stop["max_settlement_cents"] for stop in instance["stops"]}
    marginal_rows = []
    for index, identifier in enumerate(order_ids):
        upper = min(caps[identifier], payload["total_cost_cents"])
        for amount in range(1, upper + 1):
            marginal_rows.append(
                (Fraction(2 * amount - 1) - 2 * exact[identifier], -index, identifier)
            )
    marginal_rows.sort()
    allocation = {identifier: 0 for identifier in order_ids}
    for _marginal, _index, identifier in marginal_rows[: payload["total_cost_cents"]]:
        allocation[identifier] += 1
    return {
        "settlement_cents": allocation,
        "allocated_total_cents": sum(allocation.values()),
        "rounding_remainder_cents": payload["total_cost_cents"] - sum(allocation.values()),
    }


def full_reference(instance, dynamic_routes=False):
    """Run the independent three-stage reference calculation."""
    coalitions = route_reference_dp(instance) if dynamic_routes else route_reference(instance)
    shares = shapley_reference(instance, {"coalitions": coalitions})
    settlement = settlement_reference(shares, instance)
    return {
        "instance_id": instance["instance_id"],
        "coalitions": coalitions,
        "shares": shares["shares"],
        "settlement_cents": settlement["settlement_cents"],
        "total_cost_cents": shares["total_cost_cents"],
        "rounding_remainder_cents": settlement["rounding_remainder_cents"],
    }


def test_c1_single_order_round_trip():
    """Match the sole tour and its single rounded total."""
    instance = make_instance(["A"], [(2400, 1800)], factor=1.25, rate=310, fee=700)
    expected = route_reference(instance)
    actual = run_json("coalitions", [instance])
    assert actual == {"instance_id": instance["instance_id"], "coalitions": expected}


def test_c1_two_order_direction_matters():
    """Choose the cheaper of two closed two-stop directions."""
    instance = make_instance(["A", "B"], [(800, 0), (5200, 0)], factor=1.1, rate=420, fee=1500)
    expected = route_reference(instance)
    actual = run_json("coalitions", [instance])
    assert actual == {"instance_id": instance["instance_id"], "coalitions": expected}


def test_c1_nearest_neighbor_global_tour():
    """Recover the global tour where the nearest first stop is not optimal."""
    instance = json.loads((WORKSPACE / "example.json").read_text(encoding="utf-8"))
    expected = route_reference(instance)
    actual = run_json("coalitions", [instance])
    assert actual == {"instance_id": instance["instance_id"], "coalitions": expected}


def test_c1_lexicographic_tie_break():
    """Break an equal-distance tour tie by the ordered stop identifiers."""
    instance = make_instance(["A2", "A1"], [(3000, 0), (3000, 0)], factor=1.0, rate=100, fee=0)
    expected = route_reference(instance)
    actual = run_json("coalitions", [instance])
    assert actual == {"instance_id": instance["instance_id"], "coalitions": expected}


def test_c2_two_order_marginals():
    """Split a two-order saving by the two exact marginal contributions."""
    instance = make_instance(["A", "B"], [(1000, 0), (2000, 0)])
    values = {("A",): 100, ("B",): 100, ("A", "B"): 150}
    coalition_file = coalition_payload(instance, lambda members: values[members])
    expected = shapley_reference(instance, coalition_file)
    actual = run_json("shapley", [instance, coalition_file])
    assert actual == expected


def test_c2_four_order_exact_fractions():
    """Match every reduced Shapley fraction on a non-additive four-order game."""
    instance = make_instance(
        ["A1", "A2", "A3", "A4"],
        [(900, 0), (1800, 1200), (2900, -700), (4100, 300)],
    )

    def values(members):
        """Return the fixed four-order coalition cost for these members."""
        base = 70 * len(members) + sum(13 * int(member[1:]) for member in members)
        bonus = 41 if {"A1", "A4"} <= set(members) else 0
        discount = 19 if {"A2", "A3"} <= set(members) else 0
        return base + bonus - discount

    coalition_file = coalition_payload(instance, values)
    expected = shapley_reference(instance, coalition_file)
    actual = run_json("shapley", [instance, coalition_file])
    assert actual == expected


def test_c2_additive_game_identity():
    """Return each order's own weight when the value function is additive."""
    instance = make_instance(
        ["N1", "N2", "N3"],
        [(-1200, 400), (2100, -900), (3400, 1900)],
    )
    weights = {"N1": 37, "N2": 59, "N3": 83}
    coalition_file = coalition_payload(instance, lambda members: sum(weights[item] for item in members))
    expected = shapley_reference(instance, coalition_file)
    actual = run_json("shapley", [instance, coalition_file])
    assert actual == expected


def test_c2_missing_coalition_rejected():
    """Reject an incomplete coalition file without creating a result."""
    instance = make_instance(["A", "B"], [(1000, 0), (2000, 0)])
    coalition_file = coalition_payload(instance, lambda members: 100 * len(members))
    coalition_file["coalitions"].pop()
    status, raw, _stderr = invoke("shapley", [instance, coalition_file])
    assert status != 0 and raw is None


def test_c3_three_way_tie():
    """Break a final marginal tie toward the lexicographically smaller vector."""
    instance = make_instance(
        ["N1", "N2", "N3"],
        [(100, 0), (200, 0), (300, 0)],
        caps={"N1": 4, "N2": 4, "N3": 4},
    )
    payload = share_payload(10, {"N3": Fraction(10, 3), "N1": Fraction(10, 3), "N2": Fraction(10, 3)})
    expected = settlement_reference(payload, instance)
    actual = run_json("settle", [instance, payload])
    assert actual == expected


def test_c3_multiple_equal_fractions():
    """Allocate two cents when two fractions tie above the third."""
    instance = make_instance(
        ["A", "B", "C"],
        [(100, 0), (200, 0), (300, 0)],
        caps={"A": 6, "B": 6, "C": 6},
    )
    payload = share_payload(
        10,
        {"C": Fraction(5, 2), "A": Fraction(15, 4), "B": Fraction(15, 4)},
    )
    expected = settlement_reference(payload, instance)
    actual = run_json("settle", [instance, payload])
    assert actual == expected


def test_c3_irreducible_fraction_required():
    """Reject an unreduced share instead of silently normalizing it."""
    instance = make_instance(
        ["A"],
        [(100, 0)],
        caps={"A": 5},
    )
    payload = {
        "shares": [{"order_id": "A", "numerator": 2, "denominator": 4}],
        "total_cost_cents": 1,
        "efficiency_holds": True,
    }
    status, raw, _stderr = invoke("settle", [instance, payload])
    assert status != 0 and raw is None


def test_c3_existing_output_preserved():
    """Leave an existing result untouched when the share file is invalid."""
    instance = make_instance(
        ["A"],
        [(100, 0)],
        caps={"A": 5},
    )
    cases = [
        {
            "shares": [{"order_id": "A", "numerator": -1, "denominator": 1}],
            "total_cost_cents": -1,
            "efficiency_holds": True,
        },
        {
            "shares": [{"order_id": "A", "numerator": 1, "denominator": 1}],
            "total_cost_cents": 2,
            "efficiency_holds": True,
        },
        {
            "shares": [{"order_id": "A", "numerator": 1, "denominator": 0}],
            "total_cost_cents": 1,
            "efficiency_holds": True,
        },
    ]
    observed = [
        invoke("settle", [instance, case], existing="previous result")
        for case in cases
    ]
    assert all(status != 0 and raw == "previous result" for status, raw, _stderr in observed)


def test_c3_binding_cap_reallocates():
    """Move cents away from a capped order while minimizing squared error."""
    instance = make_instance(
        ["A", "B", "C"],
        [(100, 0), (200, 0), (300, 0)],
        caps={"A": 4, "B": 8, "C": 8},
    )
    payload = share_payload(
        10,
        {"A": Fraction(5), "B": Fraction(3), "C": Fraction(2)},
    )
    expected = settlement_reference(payload, instance)
    actual = run_json("settle", [instance, payload])
    assert actual == expected


def test_e2e_example_instance():
    """Match all three stages on the supplied demonstration instance."""
    instance = json.loads((WORKSPACE / "example.json").read_text(encoding="utf-8"))
    expected = full_reference(instance)
    actual = run_json("run", [instance])
    assert actual == expected


def test_e2e_generated_six_stop_instance():
    """Match a second six-stop instance with two route and rounding traps."""
    generator = random.Random(481516)
    coordinates = [
        (generator.randint(-5200, 5200), generator.randint(-4700, 4700))
        for _ in range(6)
    ]
    instance = make_instance(
        ["R1", "R2", "R3", "R4", "R5", "R6"],
        coordinates,
        factor=1.27,
        rate=345,
        fee=1340,
    )
    expected = full_reference(instance)
    actual = run_json("run", [instance])
    assert actual == expected


def test_e2e_ten_stop_dynamic_programming_scale():
    """Match a ten-stop instance without enumerating every full permutation."""
    generator = random.Random(2026102201)
    coordinates = [
        (generator.randint(-6500, 6500), generator.randint(-5800, 5800))
        for _ in range(10)
    ]
    instance = make_instance(
        [f"T{index:02d}" for index in range(1, 11)],
        coordinates,
        factor=1.31,
        rate=372,
        fee=2200,
    )
    expected = full_reference(instance, dynamic_routes=True)
    actual = run_json("run", [instance])
    assert actual == expected
