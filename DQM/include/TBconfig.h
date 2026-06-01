#ifndef TBconfig_h
#define TBconfig_h 1

#include <iostream>
#include <string>

#include "yaml-cpp/yaml.h"
#include "TBplotengine.h"

class TBconfig
{
public:
    TBconfig() = default;
    TBconfig(const std::string &config_) {

        config = YAML::LoadFile(config_);
    }
    ~TBconfig(){};

    const auto &GetConfig() { return config; }

private:
    YAML::Node config;

};

#endif
