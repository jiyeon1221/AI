#ifndef TBpedConfig_h
#define TBpedConfig_h 1

#include <map>
#include <string>
#include "yaml-cpp/yaml.h"

// Per-channel pedestal window length, configurable from config_general.yml.
//
// YAML schema (top-level "PedestalBins"):
//
//   PedestalBins:
//     Default: 100               # used when no rule below matches
//     ByPrefix:                  # match if name starts with key AND
//       S: 50                    # the next character is a digit
//       C: 50                    # so "S1".."S64" / "C1".."C64" both hit
//     ByName:                    # exact channel-name override (highest prio)
//       T1-C: 80
//
// Lookup order (highest priority wins):
//   1. ByName[name]
//   2. ByPrefix[prefix] where prefix is the longest entry such that
//      name starts with `prefix` AND name[len(prefix)] is a digit
//   3. Default (constructor argument; ultimately 100 if unset)
//
// All fields are optional. Missing/empty -> rule is skipped.
//
// Lightweight header-only class; no link-time dependency beyond yaml-cpp,
// which is already pulled in by TBconfig.h.
class TBpedConfig {
public:
  TBpedConfig() : fDefault(100) {}

  // Populate (or repopulate) from a YAML node. Passing an undefined node
  // is fine — every field then keeps its compile-time default and BinsFor()
  // always returns 100. Safe to call multiple times.
  void Load(const YAML::Node& node) {
    fByName.clear();
    fByPrefix.clear();
    fDefault = 100;

    if (!node || !node.IsDefined() || node.IsNull()) return;

    if (node["Default"] && node["Default"].IsScalar()) {
      const int v = node["Default"].as<int>();
      if (v > 0) fDefault = v;
    }

    if (node["ByPrefix"] && node["ByPrefix"].IsMap()) {
      for (const auto& kv : node["ByPrefix"]) {
        const std::string key = kv.first.as<std::string>();
        const int v = kv.second.as<int>();
        if (!key.empty() && v > 0) fByPrefix[key] = v;
      }
    }

    if (node["ByName"] && node["ByName"].IsMap()) {
      for (const auto& kv : node["ByName"]) {
        const std::string key = kv.first.as<std::string>();
        const int v = kv.second.as<int>();
        if (!key.empty() && v > 0) fByName[key] = v;
      }
    }
  }

  int Default() const { return fDefault; }

  // Resolve the pedestal window length for a given channel name.
  // Empty name -> Default (so callers that don't know the name still work).
  int BinsFor(const std::string& name) const {
    if (name.empty()) return fDefault;

    auto itName = fByName.find(name);
    if (itName != fByName.end()) return itName->second;

    // Longest-prefix-with-digit-suffix wins, so an entry "SiPM" would beat
    // "S" for a channel named "SiPM3". Tiny linear scan; map sizes are
    // expected to be ~O(1) in practice.
    int best = -1;
    int bestLen = -1;
    for (const auto& kv : fByPrefix) {
      const std::string& prefix = kv.first;
      const size_t plen = prefix.size();
      if (plen == 0 || name.size() <= plen) continue;
      if (name.compare(0, plen, prefix) != 0) continue;
      const char next = name[plen];
      if (next < '0' || next > '9') continue;
      if (static_cast<int>(plen) > bestLen) {
        bestLen = static_cast<int>(plen);
        best = kv.second;
      }
    }
    if (best > 0) return best;

    return fDefault;
  }

private:
  int fDefault;
  std::map<std::string, int> fByName;
  std::map<std::string, int> fByPrefix;
};

#endif
