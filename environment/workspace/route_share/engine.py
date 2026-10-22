from .game import build_shares
from .routing import build_coalitions
from .settlement import settle_shares, validate_instance


def coalitions_payload(instance):
    validate_instance(instance)
    return {
        "instance_id": instance["instance_id"],
        "coalitions": build_coalitions(instance),
    }


def shapley_payload(instance, coalition_payload):
    validate_instance(instance)
    return build_shares(instance, coalition_payload)


def run_all(instance):
    coalition_result = coalitions_payload(instance)
    share_result = shapley_payload(instance, coalition_result)
    settled = settle_shares(instance, share_result)
    return {
        "instance_id": instance["instance_id"],
        "coalitions": coalition_result["coalitions"],
        "shares": share_result["shares"],
        "settlement_cents": settled["settlement_cents"],
        "total_cost_cents": share_result["total_cost_cents"],
        "rounding_remainder_cents": settled["rounding_remainder_cents"],
    }
