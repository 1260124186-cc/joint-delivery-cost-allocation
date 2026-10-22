"""Run baseline, one-fix specimens, and bypass specimens through the real test script."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


TASK = Path(__file__).resolve().parents[1]
IMAGE = "harbor-quality:joint-delivery-cost-allocation"
GROUPS = ("c1", "c2", "c3", "e2e")


def run_command(args, **kwargs):
    """Run a command without raising on a non-zero status."""
    return subprocess.run(args, text=True, capture_output=True, check=False, **kwargs)


def copy_file(source, destination):
    """Copy one solution module into a specimen workspace."""
    shutil.copy2(TASK / "solution" / source, destination)


def specimen(root, label, files, override=None):
    """Execute a candidate workspace against the real test entry point."""
    work = root / label / "workspace"
    shutil.copytree(TASK / "environment" / "workspace", work)
    for entry in files:
        if isinstance(entry, tuple):
            source, destination = entry
        else:
            source = destination = entry
        copy_file(source, work / "route_share" / destination)
    if override is not None:
        override(work)
    logs = root / label / "logs" / "verifier"
    logs.mkdir(parents=True)
    (root / label).chmod(0o755)
    logs.parent.chmod(0o777)
    logs.chmod(0o777)
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        "10001:10001",
        "--network",
        "host",
        "-v",
        f"{work}:/workspace:ro",
        "-v",
        f"{TASK / 'tests'}:/tests:ro",
        "-v",
        f"{logs.parent}:/logs",
        IMAGE,
        "bash",
        "/tests/test.sh",
    ]
    outcome = run_command(command)
    reward_path = logs / "reward.txt"
    reward = float(reward_path.read_text(encoding="utf-8").strip()) if reward_path.exists() else None
    evidence = TASK / "solution" / "evidence" / f"{label}.log"
    group_logs = {}
    for group in GROUPS:
        group_log = logs / f"{group}.log"
        group_logs[group] = group_log.read_text(encoding="utf-8") if group_log.exists() else "missing"
    evidence.write_text(
        "Command: "
        + " ".join(command)
        + f"\nExit: {outcome.returncode}\nReward: {reward}\n"
        + "stdout:\n"
        + outcome.stdout
        + "\nstderr:\n"
        + outcome.stderr
        + "".join(f"\n[{group}]\n{log}" for group, log in group_logs.items()),
        encoding="utf-8",
    )
    if reward is None:
        raise RuntimeError(f"{label}: no reward; inspect {evidence}")
    print(f"{label}: {reward}")
    return {"reward": reward, "evidence": str(evidence.relative_to(TASK))}


def empty_engine(work):
    """Replace the pipeline with empty stage payloads."""
    (work / "route_share" / "engine.py").write_text(
        "def coalitions_payload(instance):\n"
        "    return {}\n\n"
        "def shapley_payload(instance, coalition_payload):\n"
        "    return {}\n\n"
        "def run_all(instance):\n"
        "    return {}\n",
        encoding="utf-8",
    )


def fixed_example(work, result, settlement):
    """Return the same canned example payload for every input."""
    fixed_path = work / "route_share" / "fixed.json"
    fixed_path.write_text(
        json.dumps({"run": result, "settlement": settlement}),
        encoding="utf-8",
    )
    (work / "route_share" / "engine.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "FIXED = json.loads(Path(__file__).with_name('fixed.json').read_text())\n\n"
        "def coalitions_payload(instance):\n"
        "    return {'instance_id': instance['instance_id'], "
        "'coalitions': FIXED['run']['coalitions']}\n\n"
        "def shapley_payload(instance, coalition_payload):\n"
        "    return {'shares': FIXED['run']['shares'], "
        "'total_cost_cents': FIXED['run']['total_cost_cents'], "
        "'efficiency_holds': True}\n\n"
        "def run_all(instance):\n"
        "    return FIXED['run']\n",
        encoding="utf-8",
    )
    (work / "route_share" / "settlement.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "FIXED = json.loads(Path(__file__).with_name('fixed.json').read_text())\n\n"
        "def validate_instance(instance):\n"
        "    return None\n\n"
        "def settle_shares(payload):\n"
        "    return FIXED['settlement']\n",
        encoding="utf-8",
    )


def drop_settlement(work):
    """Remove the settlement implementation."""
    (work / "route_share" / "settlement.py").unlink()


def main():
    """Build the image, execute all specimens, and write the experiment matrix."""
    build = run_command(["docker", "build", "-q", "-t", IMAGE, str(TASK / "environment")])
    if build.returncode:
        raise RuntimeError(build.stderr)
    (TASK / "solution" / "evidence").mkdir(exist_ok=True)

    import importlib.util

    def load_module(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    routing = load_module("reference_routing", TASK / "solution" / "routing.py")
    game = load_module("reference_game", TASK / "solution" / "game.py")
    settlement = load_module("reference_settlement", TASK / "solution" / "settlement.py")
    instance = json.loads((TASK / "environment" / "workspace" / "example.json").read_text())
    coalitions = routing.build_coalitions(instance)
    shares = game.build_shares(instance, {"coalitions": coalitions})
    settled = settlement.settle_shares(instance, shares)
    fixed = {
        "instance_id": instance["instance_id"],
        "coalitions": coalitions,
        "shares": shares["shares"],
        "settlement_cents": settled["settlement_cents"],
        "total_cost_cents": shares["total_cost_cents"],
        "rounding_remainder_cents": settled["rounding_remainder_cents"],
    }

    with tempfile.TemporaryDirectory(prefix="joint-delivery-quality-") as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        baseline = specimen(root, "baseline", [])
        oracle = specimen(root, "oracle", ["routing.py", "game.py", "settlement.py"])
        partials = [
            {"challenge_id": "C1", **specimen(root, "partial-c1", ["routing.py"])},
            {"challenge_id": "C2", **specimen(root, "partial-c2", ["game.py"])},
            {"challenge_id": "C3", **specimen(root, "partial-c3", ["settlement.py"])},
        ]
        bypasses = [
            {
                "id": "B1",
                "description": "各阶段只返回空对象",
                **specimen(root, "bypass-empty", [], empty_engine),
            },
            {
                "id": "B2",
                "description": "固定返回公开示例的计算结果",
                **specimen(
                    root,
                    "bypass-fixed",
                    [],
                    lambda work: fixed_example(work, fixed, settled),
                ),
            },
            {
                "id": "B3",
                "description": "删除整数结算模块",
                **specimen(root, "bypass-delete", [], drop_settlement),
            },
        ]

    report = {
        "baseline": baseline,
        "oracle": oracle,
        "partials": partials,
        "bypasses": bypasses,
    }
    (TASK / "solution" / "quality-gate-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if baseline["reward"] != 0 or oracle["reward"] != 1:
        raise RuntimeError("baseline/oracle gate failed")
    if any(not 0 < entry["reward"] < 1 for entry in partials):
        raise RuntimeError("partial gate failed")
    if any(entry["reward"] == 1 for entry in bypasses):
        raise RuntimeError("bypass gate failed")


if __name__ == "__main__":
    main()
