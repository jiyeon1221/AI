#!/bin/bash
# ── Compile a standalone DQM executable ────────────────────────
# Usage:  bash compile.sh TBxxx.cc
#         bash compile.sh monit.cc
#
# Works from DQM/ or any subdirectory (e.g. monit_ref/).
# Automatically locates install/ relative to DQM/.

set -e

if [ -z "$1" ]; then
  echo "Usage: bash compile.sh <source.cc>"
  exit 1
fi

ext="${1##*.}"
fname="$(basename "$1" ".$ext")"
echo "Compiling $fname.cc → $fname"

# Locate DQM root (where install/ lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_DIR/install" ]; then
  DQM_ROOT="$SCRIPT_DIR"
elif [ -d "$SCRIPT_DIR/../install" ]; then
  DQM_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  echo "Error: install/ directory not found"
  exit 1
fi

# yaml-cpp
if [ -d "/opt/homebrew/opt/yaml-cpp" ]; then
  YAMLPATH=/opt/homebrew/opt/yaml-cpp
elif [ -d "/Users/Shared/cvmfs/sft.cern.ch/lcg/releases/yamlcpp/0.6.3-d05b2/arm64-mac15-clang170-opt" ]; then
  YAMLPATH=/Users/Shared/cvmfs/sft.cern.ch/lcg/releases/yamlcpp/0.6.3-d05b2/arm64-mac15-clang170-opt
else
  echo "Error: yaml-cpp not found!"
  exit 1
fi

g++ \
  -I"$DQM_ROOT/install/include" \
  -I"$YAMLPATH/include" \
  -L"$DQM_ROOT/install/lib" \
  -L"$YAMLPATH/lib" \
  -Wl,-rpath,"$DQM_ROOT/install/lib" \
  "$DQM_ROOT/install/lib/libdrcTB.dylib" \
  -lyaml-cpp \
  $(root-config --cflags --libs) \
  "$fname.cc" -o "$fname"

echo "Done! → ./$fname"
