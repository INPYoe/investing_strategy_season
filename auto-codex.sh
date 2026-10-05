#!/bin/bash
# Keep one Codex session working through TODO.md. Run this script explicitly.
set -uo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
  echo "사용법: $0 '첫 작업 지시'" >&2
  exit 64
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1
cd -- "$SCRIPT_DIR" || exit 1
for executable in codex python3; do
  command -v "$executable" >/dev/null || exit 127
done
[[ -f TODO.md ]] || { echo 'TODO.md가 필요합니다.' >&2; exit 1; }

FIRST_PROMPT="$1"
CONTINUE_PROMPT='TODO.md와 CONTINUE.md를 확인하고 미완료 항목부터 이어서 진행해줘.'
COMPLETION_RULE='불일치 분석 → 전역 계산 가설 수정 → 테스트 → 비교를 반복해줘. 특정 사례 하드코딩, 기준값 변경, 허용오차 완화는 금지하고 사이트 재현 모드와 투자 모드를 구분해줘. 새 종목·미사용 기간도 검증해줘. 실행 근거를 TODO.md에 기록하고 실제로 완료한 항목만 체크해줘. 모든 미완료 항목과 전체 사이트 재현 검증이 끝난 경우에만 마지막 줄에 ALL_DONE 이라고 출력해. 이 스크립트 자체를 실행하거나 다른 Codex 반복 루프를 시작하지 마.'
LAST_MESSAGE_FILE="$SCRIPT_DIR/auto-codex-last-message.txt"
SESSION_ID=''
NEXT_PROMPT="$FIRST_PROMPT $COMPLETION_RULE"

while true; do
  # Remove stale completion evidence before each invocation.
  : > "$LAST_MESSAGE_FILE" || exit 1
  CODEX_ARGS=(exec --approve-for-me --sandbox workspace-write)
  if [[ -n "$SESSION_ID" ]]; then
    CODEX_ARGS+=(resume "$SESSION_ID")
  fi
  CODEX_ARGS+=(--skip-git-repo-check --json --output-last-message "$LAST_MESSAGE_FILE" "$NEXT_PROMPT")
  codex "${CODEX_ARGS[@]}" 2>&1 | tee log.txt
  PIPE_RESULTS=("${PIPESTATUS[@]}")
  CODEX_STATUS="${PIPE_RESULTS[0]}"
  [[ "${PIPE_RESULTS[1]}" -eq 0 ]] || { echo '로그 저장 실패' >&2; exit 1; }

  # Parse only actual CLI errors, not agent/tool messages mentioning a limit.
  EVENT_STATE="$(python3 - log.txt <<'PY'
import json
import re
import sys

thread_id = ''
errors = []
with open(sys.argv[1], encoding='utf-8', errors='replace') as stream:
    for line in stream:
        try:
            event = json.loads(line)
        except ValueError:
            if re.match(r'\s*(?:error\b|fatal\b|you(?:\x27ve| have) hit\b|rate[ _-]limit\b|usage[ _-]limit\b)',
                        line, re.IGNORECASE):
                errors.append(line)
            continue
        if not isinstance(event, dict):
            continue
        if event.get('type') == 'thread.started':
            thread_id = event.get('thread_id') or thread_id
        if event.get('type') in ('error', 'turn.failed'):
            errors.append(json.dumps(event, ensure_ascii=False))
pattern = r'usage[ _-]limit|rate[ _-]limit|usage_limit_reached|rate_limit_exceeded'
print(thread_id)
print(int(bool(re.search(pattern, '\n'.join(errors), re.IGNORECASE))))
PY
  )" || exit 1
  FOUND_SESSION="${EVENT_STATE%%$'\n'*}"
  LIMIT_REACHED="${EVENT_STATE##*$'\n'}"
  if [[ -n "$FOUND_SESSION" ]]; then
    if [[ -n "$SESSION_ID" && "$SESSION_ID" != "$FOUND_SESSION" ]]; then
      echo '예상과 다른 세션이 반환되어 중단합니다.' >&2
      exit 1
    fi
    SESSION_ID="$FOUND_SESSION"
  fi

  if [[ "$CODEX_STATUS" -ne 0 ]]; then
    if [[ "$LIMIT_REACHED" == 1 ]]; then
      echo "[$(date)] 한도 도달 - 30분 후 같은 작업을 다시 시도합니다"
      sleep 1800 || exit 130
      continue
    fi
    echo "[$(date)] Codex 실행 실패 (종료 코드 $CODEX_STATUS). log.txt를 확인하세요." >&2
    exit "$CODEX_STATUS"
  fi

  LAST_LINE="$(awk 'NF { line=$0 } END { sub(/\r$/, "", line); print line }' "$LAST_MESSAGE_FILE")"
  if [[ "$LAST_LINE" == ALL_DONE ]]; then
    [[ -f TODO.md ]] || { echo 'TODO.md가 사라져 완료를 확인할 수 없습니다.' >&2; exit 1; }
    if ! grep -qE '^[[:space:]]*- \[ \]' TODO.md; then
      echo "[$(date)] 작업 완료!"
      exit 0
    fi
    echo '미완료 TODO가 남아 있어 계속 진행합니다.' >&2
  fi
  [[ -n "$SESSION_ID" ]] || { echo '이어갈 세션 ID가 없어 중단합니다.' >&2; exit 1; }
  NEXT_PROMPT="$CONTINUE_PROMPT $COMPLETION_RULE"
done
