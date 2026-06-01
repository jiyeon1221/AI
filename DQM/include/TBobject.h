#ifndef TBobject_h
#define TBobject_h 1

#include <map>
#include <iostream>
#include <vector>
#include <stdexcept>
#include <stdio.h>
#include <stdlib.h>
#include <string>
#include <chrono>
#include <cmath>
#include <numeric>
#include <functional>

#include "TBread.h"

class ObjectCollection
{
public:
  ObjectCollection(int argc, char* argv[]);
  ~ObjectCollection() {}

  void init();
  bool Help();

  void AddVariable(std::string key, bool value) { fVarBool[key] = value; }
  void AddVariable(std::string key, int value) { fVarInt[key] = value; }
  void AddVariable(std::string key, double value) { fVarDouble[key] = value; }
  void AddVariable(std::string key, std::string value) { fVarString[key] = value; }

  void AddVec(std::string key, int value) { fVarIntVec[key].push_back(value); }
  void AddVec(std::string key, double value) { fVarDoubleVec[key].push_back(value); }
  void AddVec(std::string key, std::string value) { fVarStringVec[key].push_back(value); }

  void GetVariable(std::string key, bool* value);
  void GetVariable(std::string key, int* value);
  void GetVariable(std::string key, double* value);
  void GetVariable(std::string key, std::string* value);

  void GetVector(std::string key, std::vector<int>* value);
  void GetVector(std::string key, std::vector<double>* value);
  void GetVector(std::string key, std::vector<std::string>* value);

  void Print();


private:

  int fArgc;
  std::vector<std::string> fArgv;

  std::map<std::string, bool> fVarBool;

  std::map<std::string, int> fVarInt;
  std::map<std::string, std::vector<int>> fVarIntVec;

  std::map<std::string, double> fVarDouble;
  std::map<std::string, std::vector<double>> fVarDoubleVec;

  std::map<std::string, std::string> fVarString;
  std::map<std::string, std::vector<std::string>> fVarStringVec;

};

#endif
