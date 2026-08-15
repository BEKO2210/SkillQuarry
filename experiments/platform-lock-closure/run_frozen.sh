#!/usr/bin/env bash
set -uo pipefail

ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

pairs_pass=0
pairs_miss=0
pairs_infra=0
repaired_witnesses=0

record() {
  local pair="$1" status="$2" detail="$3"
  printf 'RESULT pair=%s status=%s detail=%q\n' "$pair" "$status" "$detail"
  case "$status" in
    PASS) pairs_pass=$((pairs_pass+1)) ;;
    MISS|FAIL) pairs_miss=$((pairs_miss+1)) ;;
    INFRA) pairs_infra=$((pairs_infra+1)) ;;
  esac
}

clone_at() {
  local repo="$1" sha="$2" dest="$3"
  git clone --quiet --filter=blob:none --no-checkout "https://github.com/${repo}.git" "$dest" || return 1
  git -C "$dest" checkout --quiet "$sha" || return 1
}

npm_has_witness() {
  python3 - "$1" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
print('1' if 'node_modules/@rollup/rollup-linux-x64-gnu' in data.get('packages', {}) else '0')
PY
}

run_npm_revision() {
  local label="$1" sha="$2"
  local dir="$ROOT/firecms-$label"
  if ! clone_at firecmsco/firecms "$sha" "$dir"; then
    printf 'REV manager=npm revision=%s status=INFRA detail=clone_failed\n' "$label"
    return 2
  fi
  pushd "$dir" >/dev/null || return 2
  rm -rf node_modules
  local before after rc
  before="$(npm_has_witness package-lock.json)" || { popd >/dev/null; return 2; }
  cp package-lock.json "$ROOT/firecms-$label-before.json"

  # FireCMS' historical workflow used Node 20. Pin Node 20 and npm 10 in an
  # isolated Linux container so the pnpm case can independently use Node 22.
  docker run --rm \
    -v "$dir:/repo" -w /repo \
    node:20-bookworm \
    bash -lc 'npm install -g npm@10 >/dev/null 2>&1 && printf "H1_TOOL node=%s npm=%s\n" "$(node --version)" "$(npm --version)" && npm install --package-lock-only --ignore-scripts --include=optional --no-audit --no-fund' \
    >/tmp/firecms-$label.log 2>&1
  rc=$?
  cat /tmp/firecms-$label.log
  if [[ $rc -ne 0 ]]; then
    popd >/dev/null
    printf 'REV manager=npm revision=%s status=INFRA detail=npm_lock_normalization_failed\n' "$label"
    return 2
  fi
  after="$(npm_has_witness package-lock.json)" || { popd >/dev/null; return 2; }
  popd >/dev/null
  printf 'REV manager=npm revision=%s before=%s after=%s witness=@rollup/rollup-linux-x64-gnu\n' "$label" "$before" "$after"
  if [[ "$label" == broken ]]; then
    [[ "$before" == 0 && "$after" == 1 ]]
  else
    [[ "$before" == 1 && "$after" == 1 ]]
  fi
}

pnpm_has_arm_witnesses() {
  local lock="$1"
  local n=0
  grep -Fq "@promptctl/cc-candybar-darwin-arm64" "$lock" && n=$((n+1))
  grep -Fq "@promptctl/cc-candybar-linux-arm64" "$lock" && n=$((n+1))
  printf '%s\n' "$n"
}

run_pnpm_revision() {
  local label="$1" sha="$2"
  local dir="$ROOT/candybar-$label"
  if ! clone_at promptctl/cc-candybar "$sha" "$dir"; then
    printf 'REV manager=pnpm revision=%s status=INFRA detail=clone_failed\n' "$label"
    return 2
  fi
  pushd "$dir" >/dev/null || return 2
  rm -rf node_modules
  local before after rc
  before="$(pnpm_has_arm_witnesses pnpm-lock.yaml)"
  cp pnpm-lock.yaml "$ROOT/candybar-$label-before.yaml"
  printf 'H2_TOOL node=%s pnpm=%s\n' "$(node --version)" "$(pnpm --version)"
  pnpm install --lockfile-only --ignore-scripts --no-frozen-lockfile >/tmp/candybar-$label.log 2>&1
  rc=$?
  cat /tmp/candybar-$label.log
  if [[ $rc -ne 0 ]]; then
    popd >/dev/null
    printf 'REV manager=pnpm revision=%s status=INFRA detail=pnpm_lock_normalization_failed\n' "$label"
    return 2
  fi
  after="$(pnpm_has_arm_witnesses pnpm-lock.yaml)"
  popd >/dev/null
  printf 'REV manager=pnpm revision=%s before=%s after=%s arm_witness_count\n' "$label" "$before" "$after"
  if [[ "$label" == broken ]]; then
    [[ "$before" -lt 2 && "$after" -gt "$before" ]]
  else
    [[ "$before" -eq 2 && "$after" -eq 2 ]]
  fi
}

bundle_snapshot() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
s = Path(sys.argv[1]).read_text()
w = [
    'x86_64-linux',
    'ffi (1.17.4-x86_64-linux-gnu)',
    'google-protobuf (4.34.1-x86_64-linux-gnu)',
    'sass-embedded (1.98.0-x86_64-linux-gnu)',
]
print(sum(x in s for x in w))
PY
}

run_bundle_revision() {
  local label="$1" sha="$2"
  local dir="$ROOT/site-$label"
  if ! clone_at gmackie/personalWebsite "$sha" "$dir"; then
    printf 'REV manager=bundler revision=%s status=INFRA detail=clone_failed\n' "$label"
    return 2
  fi
  pushd "$dir" >/dev/null || return 2
  local before after rc
  before="$(bundle_snapshot Gemfile.lock)"
  cp Gemfile.lock "$ROOT/site-$label-before.lock"
  printf 'H3_TOOL ruby=%s bundler=%s\n' "$(ruby --version | awk '{print $2}')" "$(bundle _2.4.6_ --version | awk '{print $3}')"
  bundle _2.4.6_ lock --add-platform x86_64-linux >/tmp/site-$label.log 2>&1
  rc=$?
  cat /tmp/site-$label.log
  if [[ $rc -ne 0 ]]; then
    popd >/dev/null
    printf 'REV manager=bundler revision=%s status=INFRA detail=bundle_lock_failed\n' "$label"
    return 2
  fi
  after="$(bundle_snapshot Gemfile.lock)"
  popd >/dev/null
  printf 'REV manager=bundler revision=%s before=%s after=%s witness_count_of_4\n' "$label" "$before" "$after"
  if [[ "$label" == broken ]]; then
    [[ "$before" -lt 4 && "$after" -ge 2 && "$after" -gt "$before" ]]
  else
    [[ "$before" -eq 4 && "$after" -eq 4 ]]
  fi
}

run_pair() {
  local pair="$1" fn="$2" broken="$3" fixed="$4"
  local b_rc f_rc
  "$fn" broken "$broken"; b_rc=$?
  "$fn" fixed "$fixed"; f_rc=$?

  if [[ $b_rc -eq 2 || $f_rc -eq 2 ]]; then
    record "$pair" INFRA "broken_rc=$b_rc fixed_rc=$f_rc"
  elif [[ $b_rc -eq 0 && $f_rc -eq 0 ]]; then
    record "$pair" PASS "broken witness recovered; repaired witness absent"
  else
    if [[ $f_rc -ne 0 ]]; then
      repaired_witnesses=$((repaired_witnesses+1))
    fi
    record "$pair" MISS "broken_rc=$b_rc fixed_rc=$f_rc"
  fi
}

printf '%s\n' '=== Lock Closure Union frozen historical replay ==='
run_pair npm-firecms run_npm_revision \
  0e8919618a6bcc207e265815cea53ed6c452b5c3 \
  4e2bfb412c65aa3a131ee8d8ef35f28086d79ebe

run_pair pnpm-cc-candybar run_pnpm_revision \
  9ad9134f8b685dcc513be5165154d790da15953a \
  4d2b7c15970f66b26c339d5bc67307365cc6736c

run_pair bundler-personalWebsite run_bundle_revision \
  a96f6c8f9c895703cf050faece66918685cfe5ee \
  35e335cf0f04ff77e9543da4aebb229e0d308778

printf 'SUMMARY pairs_pass=%s pairs_miss=%s pairs_infra=%s repaired_witnesses=%s\n' \
  "$pairs_pass" "$pairs_miss" "$pairs_infra" "$repaired_witnesses"

# Frozen gate: 3/3 technically executable, >=2/3 recovered, zero repaired witnesses.
if [[ "$pairs_infra" -ne 0 || "$pairs_pass" -lt 2 || "$repaired_witnesses" -ne 0 ]]; then
  exit 1
fi
