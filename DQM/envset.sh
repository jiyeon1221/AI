#!/bin/bash
# ── DQM environment setup ──────────────────────────────────────
# Sources ROOT + Python venv + sets library paths for building
# and running DQM executables (monit, etc.).
#
# Usage:  source envset.sh        (from DQM/ directory)
#         source DQM/envset.sh    (from project root)

# ── ROOT ───────────────────────────────────────────────────────
# Homebrew ROOT (primary — matches monit link-time libraries)
if [ -f "/opt/homebrew/opt/root/bin/thisroot.sh" ]; then
  source /opt/homebrew/opt/root/bin/thisroot.sh
# Fallback: CVMFS (CERN lxplus / KEK gateway)
elif [ -f "/cvmfs/sft.cern.ch/lcg/views/LCG_102/arm64-mac12-clang131-opt/setup.sh" ]; then
  source /cvmfs/sft.cern.ch/lcg/views/LCG_102/arm64-mac12-clang131-opt/setup.sh
else
  echo "⚠️  ROOT not found (Homebrew or CVMFS). Set ROOTSYS manually."
fi

# ── Python virtual-env ─────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
if [ -f "$PROJECT_ROOT/ai/bin/activate" ]; then
  source "$PROJECT_ROOT/ai/bin/activate"
fi

# ── DQM install paths ─────────────────────────────────────────
export INSTALL_DIR_PATH="$SCRIPT_DIR/install"

export PATH="$PATH:$INSTALL_DIR_PATH/lib"
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}$INSTALL_DIR_PATH/lib"
export DYLD_LIBRARY_PATH="${DYLD_LIBRARY_PATH:+$DYLD_LIBRARY_PATH:}$INSTALL_DIR_PATH/lib"
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$INSTALL_DIR_PATH/lib"

# ── yaml-cpp ───────────────────────────────────────────────────
if [ -d "/opt/homebrew/opt/yaml-cpp" ]; then
  export YAMLPATH=/opt/homebrew/opt/yaml-cpp
elif [ -d "/Users/Shared/cvmfs/sft.cern.ch/lcg/releases/yamlcpp/0.6.3-d05b2/arm64-mac15-clang170-opt" ]; then
  export YAMLPATH=/Users/Shared/cvmfs/sft.cern.ch/lcg/releases/yamlcpp/0.6.3-d05b2/arm64-mac15-clang170-opt
fi

if [ -n "$YAMLPATH" ]; then
  export DYLD_LIBRARY_PATH="${DYLD_LIBRARY_PATH:+$DYLD_LIBRARY_PATH:}$YAMLPATH/lib"
fi
