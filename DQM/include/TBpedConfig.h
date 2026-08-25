#ifndef TBpedConfig_h
#define TBpedConfig_h 1

#include <map>
#include <string>
#include "yaml-cpp/yaml.h"

// config_general.yml의 채널별 pedestal 구간 설정.
//
//   PedestalBins:
//     Default: 100
//     ByPrefix:
//       S: 50
//       C: 50
//     ByName:
//       T1-C: 80
// 우선순위는 채널명, 가장 긴 접두사, 기본값 순이다.
class TBpedConfig {
public:
  TBpedConfig() : fDefault(100) {}

  // YAML 노드에서 설정을 다시 읽는다.
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

  // 채널명에 맞는 pedestal 구간을 반환한다.
  int BinsFor(const std::string& name) const {
    if (name.empty()) return fDefault;

    auto itName = fByName.find(name);
    if (itName != fByName.end()) return itName->second;

    // 숫자 접미사가 붙은 가장 긴 접두사를 선택한다.
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
