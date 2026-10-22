from decimal import Decimal, ROUND_HALF_UP, localcontext
from itertools import combinations


COMPARE_QUANTUM = Decimal("0.000000000000000001")


def _positions(instance):
    result = {
        instance["depot"]["id"]: (
            Decimal(instance["depot"]["x_m"]),
            Decimal(instance["depot"]["y_m"]),
        )
    }
    for stop in instance["stops"]:
        result[stop["id"]] = (Decimal(stop["x_m"]), Decimal(stop["y_m"]))
    return result


def _distance_matrix(instance):
    positions = _positions(instance)
    matrix = {}
    with localcontext() as context:
        context.prec = 50
        for left, (x1, y1) in positions.items():
            for right, (x2, y2) in positions.items():
                if left != right:
                    dx = x2 - x1
                    dy = y2 - y1
                    matrix[(left, right)] = (dx * dx + dy * dy).sqrt()
    return matrix


def _all_shortest_routes(depot, order_ids, matrix):
    count = len(order_ids)
    indices = {identifier: index for index, identifier in enumerate(order_ids)}
    states = {}
    for index, identifier in enumerate(order_ids):
        states[(1 << index, index)] = (
            matrix[(depot, identifier)],
            (index,),
        )

    for mask in range(1, 1 << count):
        for last in range(count):
            current = states.get((mask, last))
            if current is None:
                continue
            distance, path = current
            for following in range(count):
                if mask & (1 << following):
                    continue
                next_mask = mask | (1 << following)
                next_distance = distance + matrix[(order_ids[last], order_ids[following])]
                next_path = path + (following,)
                known = states.get((next_mask, following))
                if (
                    known is None
                    or next_distance < known[0]
                    or (next_distance == known[0] and next_path < known[1])
                ):
                    states[(next_mask, following)] = (next_distance, next_path)

    routes = {}
    for mask in range(1, 1 << count):
        best = None
        for last in range(count):
            if not (mask & (1 << last)):
                continue
            current = states.get((mask, last))
            if current is None:
                continue
            raw_distance = current[0] + matrix[(order_ids[last], depot)]
            distance = raw_distance.quantize(COMPARE_QUANTUM, rounding=ROUND_HALF_UP)
            candidate = (distance, current[1])
            if best is None or candidate < best:
                best = candidate
        routes[mask] = best
    return indices, routes


def _tour_cost(distance_m, instance):
    with localcontext() as context:
        context.prec = 50
        cents = (
            distance_m
            * Decimal(str(instance["road_factor"]))
            * Decimal(instance["rate_cents_per_km"])
            / Decimal(1000)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return instance["dispatch_fee_cents"] + int(cents)


def build_coalitions(instance):
    depot = instance["depot"]["id"]
    order_ids = sorted(stop["id"] for stop in instance["stops"])
    matrix = _distance_matrix(instance)
    indices, routes = _all_shortest_routes(depot, order_ids, matrix)
    rows = []
    for size in range(1, len(order_ids) + 1):
        for members in combinations(order_ids, size):
            mask = 0
            for member in members:
                mask |= 1 << indices[member]
            distance, path = routes[mask]
            order = [order_ids[index] for index in path]
            rows.append(
                {
                    "members": list(members),
                    "cost_cents": _tour_cost(distance, instance),
                    "tour": [depot] + list(order) + [depot],
                }
            )
    return rows
