#!/bin/bash
# DQM 라이브러리와 독립 실행 파일을 다시 빌드한다.
# Usage:
#   bash rebuild_all.sh                # rebuild everything
#   bash rebuild_all.sh monit          # rebuild only the listed targets
#   bash rebuild_all.sh --lib-only     # only step 1 (dylib, no executables)
#   bash rebuild_all.sh --bins-only    # only steps 2–3 (executables only)
#
# 모든 대상을 처리한 뒤 실패 항목을 요약한다.

set -u  # 정의되지 않은 변수는 오류로 처리한다.

# 스크립트 위치를 기준으로 DQM 경로를 정한다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 실행 옵션을 해석한다.
DO_LIB=1
DO_BINS=1
EXPLICIT_TARGETS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --lib-only)  DO_BINS=0 ;;
    --bins-only) DO_LIB=0  ;;
    -h|--help)
      sed -n '2,22p' "$0"
      exit 0
      ;;
    -*)
      echo "rebuild_all.sh: unknown flag '$1'" >&2
      exit 2
      ;;
    *)
      EXPLICIT_TARGETS+=("$1")
      ;;
  esac
  shift
done

# 대상을 지정하면 해당 실행 파일만 다시 연결한다.
if [ ${#EXPLICIT_TARGETS[@]} -gt 0 ] && [ "$DO_LIB" -eq 1 ] && [ "$DO_BINS" -eq 1 ]; then
  DO_LIB=0
fi

# 출력 구분선.
hr() { printf '═%.0s' {1..70}; echo; }
banner() { hr; echo "  $1"; hr; }

OK_LIST=()
FAIL_LIST=()

# DQM 동적 라이브러리를 다시 빌드한다.
if [ "$DO_LIB" -eq 1 ]; then
  banner "1/2  building libdrcTB.dylib (buildNinstall.sh)"
  if bash buildNinstall.sh; then
    OK_LIST+=("libdrcTB.dylib")
  else
    FAIL_LIST+=("libdrcTB.dylib")
    echo "FAIL: dylib build failed — executables will be skipped"
    DO_BINS=0
  fi
fi

# 환경을 적용하고 독립 실행 파일을 다시 연결한다.
if [ "$DO_BINS" -eq 1 ]; then
  banner "2/2  re-linking standalone executables (compile.sh)"

  # 컴파일에 필요한 환경 변수를 불러온다.
  # shellcheck disable=SC1091
  source ./envset.sh

  # 다시 컴파일할 소스를 선택한다.
  if [ ${#EXPLICIT_TARGETS[@]} -gt 0 ]; then
    TARGETS=()
    for t in "${EXPLICIT_TARGETS[@]}"; do
      # 대상명과 .cc 파일명을 모두 허용한다.
      src="${t%.cc}.cc"
      if [ -f "$src" ]; then
        TARGETS+=("$src")
      else
        FAIL_LIST+=("$t (no such .cc file)")
      fi
    done
  else
    # DQM 루트의 독립 실행 소스를 모두 선택한다.
    shopt -s nullglob
    TARGETS=( *.cc )
    shopt -u nullglob
  fi

  if [ ${#TARGETS[@]} -eq 0 ]; then
    echo "(nothing to compile)"
  fi

  for src in "${TARGETS[@]}"; do
    name="${src%.cc}"
    echo
    echo "──  $src  ──"
    if bash compile.sh "$src"; then
      OK_LIST+=("$name")
    else
      FAIL_LIST+=("$name")
    fi
  done
fi

# 빌드 결과를 요약한다.
echo
banner "summary"
if [ ${#OK_LIST[@]} -gt 0 ]; then
  echo "OK   (${#OK_LIST[@]}):"
  for t in "${OK_LIST[@]}"; do echo "  ✓ $t"; done
fi
if [ ${#FAIL_LIST[@]} -gt 0 ]; then
  echo "FAIL (${#FAIL_LIST[@]}):"
  for t in "${FAIL_LIST[@]}"; do echo "  ✗ $t"; done
  exit 1
fi
exit 0
