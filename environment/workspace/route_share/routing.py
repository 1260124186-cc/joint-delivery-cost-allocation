from decimal import Decimal, ROUND_HALF_UP, localcontext
from itertools import combinations


COMPARE_QUANTUM = Decimal("0.000000000000000001")


def _node_map(instance):
    nodes = {
        instance["depot"]["id"]: (
            Decimal(instance["depot"]["x_m"]),
            Decimal(instance["depot"]["y_m"]),
        )
    }
    for stop in instance["stops"]:
        nodes[stop["id"]] = (Decimal(stop["x_m"]), Decimal(stop["y_m"]))
    return nodes


def _distances(instance):
    nodes = _node_map(instance)
    result = {}
    with localcontext() as context:
        context.prec = 50
        for left, (x1, y1) in nodes.items():
            for right, (x2, y2) in nodes.items():
                if left == right:
                    continue
                dx = x2 - x1
                dy = y2 - y1
                result[(left, right)] = (dx * dx + dy * dy).sqrt()
    return result


def _best_route(depot, members, distances):
    unvisited = set(members)
    current = depot
    order = []
    while unvisited:
        following = min(unvisited, key=lambda member: (distances[(current, member)], member))
        order.append(following)
        unvisited.remove(following)
        current = following
    route = [depot] + order + [depot]
    distance = sum(
        (distances[(route[index], route[index + 1])] for index in range(len(route) - 1)),
        Decimal(0),
    ).quantize(COMPARE_QUANTUM, rounding=ROUND_HALF_UP)
    return order, distance


def _cost_cents(distance_m, instance):
    with localcontext() as context:
        context.prec = 50
        travelled = (
            distance_m
            * Decimal(str(instance["road_factor"]))
            * Decimal(instance["rate_cents_per_km"])
            / Decimal(1000)
        )
        rounded = travelled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return instance["dispatch_fee_cents"] + int(rounded)


def build_coalitions(instance):
    depot = instance["depot"]["id"]
    order_ids = sorted(stop["id"] for stop in instance["stops"])
    distances = _distances(instance)
    rows = []
    for size in range(1, len(order_ids) + 1):
        for members in combinations(order_ids, size):
            order, distance = _best_route(depot, members, distances)
            rows.append(
                {
                    "members": list(members),
                    "cost_cents": _cost_cents(distance, instance),
                    "tour": [depot] + order + [depot],
                }
            )
    return rows
