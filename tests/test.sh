#!/bin/bash
set -u

reward_file=/logs/verifier/reward.txt
mkdir -p /logs/verifier

write_reward() {
  chmod u+w "$reward_file" 2>/dev/null || true
  printf '%s\n' "$1" > "$reward_file"
  chmod 0444 "$reward_file"
}

finished=0
finish() {
  if [ "$finished" -eq 1 ]; then
    return
  fi
  finished=1
  write_reward "${1:-0}"
}

write_reward 0
trap 'finish 0' EXIT
trap 'finish 0; exit 0' INT TERM HUP

if ! python -m pip install --user --no-cache-dir --disable-pip-version-check \
  --require-hashes --only-binary=:all: -r /tests/requirements.txt; then
  finish 0
  exit 0
fi

cd /workspace || exit 0
score=0
incomplete=0
for spec in "c1 2" "c2 3" "c3 2" "e2e 3"; do
  group=${spec%% *}
  weight=${spec##* }
  report="/logs/verifier/${group}.xml"
  : > "$report"
  if timeout --signal=TERM --kill-after=5s 60s \
      python -m pytest -q /tests/test_outputs.py -k "test_${group}_" \
      --junitxml="$report" > "/logs/verifier/${group}.log" 2>&1; then
    if python - "$report" "$group" <<'PY'
import sys
import xml.etree.ElementTree as ET

path, group = sys.argv[1], sys.argv[2]
try:
    root = ET.parse(path).getroot()
except (OSError, ET.ParseError):
    raise SystemExit(1)
cases = list(root.iter("testcase"))
suites = list(root.iter("testsuite"))
names = [case.attrib.get("name", "") for case in cases]
expected_prefix = f"test_{group}_"
if (
    not cases
    or not suites
    or sum(int(suite.attrib.get("tests", "0")) for suite in suites) != len(cases)
    or sum(int(suite.attrib.get("failures", "0")) for suite in suites) != 0
    or sum(int(suite.attrib.get("errors", "0")) for suite in suites) != 0
    or sum(int(suite.attrib.get("skipped", "0")) for suite in suites) != 0
    or any(not name.startswith(expected_prefix) for name in names)
):
    raise SystemExit(1)
PY
    then
      score=$((score + weight))
    else
      incomplete=1
    fi
  else
    incomplete=1
  fi
done

# 候选进程可能留下延迟写 reward 的子进程；先等其退出，再执行最终覆盖。
sleep 4
if [ "$incomplete" -eq 1 ]; then
  : > /logs/verifier/INCOMPLETE
else
  : > /logs/verifier/COMPLETE
fi
finish "$(python - "$score" <<'PY'
import sys
print(f"{int(sys.argv[1]) / 10:.6f}")
PY
)"
trap - INT TERM HUP
exit 0
