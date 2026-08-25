#!/bin/bash
# DQM 빌드와 실행에 필요한 ROOT, Python, 라이브러리 경로를 설정한다.
#
# Usage:  source envset.sh        (from DQM/ directory)
#         source DQM/envset.sh    (from project root)
#         source ai/bin/activate  (activate sources this script)

# 가상환경과의 상호 호출을 한 번으로 제한한다.
if [ -n "${_DQM_ENVSET_RUNNING:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
_DQM_ENVSET_RUNNING=1

# Homebrew 또는 CVMFS의 ROOT 환경을 불러온다.
if [ -f "/opt/homebrew/opt/root/bin/thisroot.sh" ]; then
  source /opt/homebrew/opt/root/bin/thisroot.sh
elif [ -f "/cvmfs/sft.cern.ch/lcg/views/LCG_102/arm64-mac12-clang131-opt/setup.sh" ]; then
  source /cvmfs/sft.cern.ch/lcg/views/LCG_102/arm64-mac12-clang131-opt/setup.sh
else
  echo "⚠️  ROOT not found (Homebrew or CVMFS). Set ROOTSYS manually."
fi

# 프로젝트 Python 가상환경을 활성화한다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
if [ -z "${_DQM_ACTIVATE_RUNNING:-}" ] && [ -f "$PROJECT_ROOT/ai/bin/activate" ]; then
  source "$PROJECT_ROOT/ai/bin/activate"
fi

# DQM 설치 경로를 환경 변수에 추가한다.
export INSTALL_DIR_PATH="$SCRIPT_DIR/install"

export PATH="$PATH:$INSTALL_DIR_PATH/lib"
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}$INSTALL_DIR_PATH/lib"
export DYLD_LIBRARY_PATH="${DYLD_LIBRARY_PATH:+$DYLD_LIBRARY_PATH:}$INSTALL_DIR_PATH/lib"
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$INSTALL_DIR_PATH/lib"

# yaml-cpp 설치 경로를 찾는다.
if [ -d "/opt/homebrew/opt/yaml-cpp" ]; then
  export YAMLPATH=/opt/homebrew/opt/yaml-cpp
elif [ -d "/Users/Shared/cvmfs/sft.cern.ch/lcg/releases/yamlcpp/0.6.3-d05b2/arm64-mac15-clang170-opt" ]; then
  export YAMLPATH=/Users/Shared/cvmfs/sft.cern.ch/lcg/releases/yamlcpp/0.6.3-d05b2/arm64-mac15-clang170-opt
fi

if [ -n "$YAMLPATH" ]; then
  export DYLD_LIBRARY_PATH="${DYLD_LIBRARY_PATH:+$DYLD_LIBRARY_PATH:}$YAMLPATH/lib"
fi

unset _DQM_ENVSET_RUNNING
