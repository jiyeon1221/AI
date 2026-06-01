#include "TButility.h"

#include <iostream>
#include <stdexcept>
#include <fstream>

void TButility::LoadMapping(const std::string &path)
{

  int mid = 0;
	int ch = 0;
	TString* name = nullptr;
	int isCeren = 0;
	int row = 0;
	int column = 0;

  std::cout << "Loading mapping file : " << path << std::endl;

  TChain *mapChain_DAQ = new TChain("mapping_DAQ");
  mapChain_DAQ->Add((TString)path);

  mapChain_DAQ->SetBranchAddress("mid", &mid);
  mapChain_DAQ->SetBranchAddress("ch", &ch);
  mapChain_DAQ->SetBranchAddress("name", &name);

  for (int i = 0; i < mapChain_DAQ->GetEntries(); i++) {
    mapChain_DAQ->GetEntry(i);

    // if (*name == "null")
    //   continue;

    TBcid aCID = TBcid(mid, ch);
    mapping_CID_NAME.insert(std::make_pair(aCID, *name));
    mapping_NAME_CID.insert(std::make_pair(*name, aCID));
  }

  TChain *mapChain_DQM = new TChain("mapping_DQM");
  mapChain_DQM->Add((TString)path);

  mapChain_DQM->SetBranchAddress("name", &name);
  mapChain_DQM->SetBranchAddress("isCeren", &isCeren);
  mapChain_DQM->SetBranchAddress("row", &row);
  mapChain_DQM->SetBranchAddress("column", &column);

  for (int i = 0; i < mapChain_DQM->GetEntries(); i++) {
    mapChain_DQM->GetEntry(i);

    // if (*name == "null")
    //   continue;

    mapping_NAME_INFO.insert(std::make_pair(*name, mod_info(isCeren, row, column)));
    mapping_CID_INFO.insert(std::make_pair(GetCID(*name), mod_info(isCeren, row, column)));
  }

  delete mapChain_DAQ;
  delete mapChain_DQM;
}

TBcid TButility::GetCID(TString name) const {
  if (mapping_NAME_CID.find(name) == mapping_NAME_CID.end()) return TBcid(-1, -1);
  else return mapping_NAME_CID.at(name);
}

std::string TButility::GetName(TBcid cid) const {
  if (mapping_CID_NAME.find(cid) == mapping_CID_NAME.end()) return "null";
  else return mapping_CID_NAME.at(cid);
}

TButility::mod_info TButility::GetInfo(TBcid cid) const {
  if (mapping_CID_INFO.find(cid) == mapping_CID_INFO.end()) return mod_info(-1, -1, -1);
  else return mapping_CID_INFO.at(cid);
}

TButility::mod_info TButility::GetInfo(TString name) const {
  if (mapping_NAME_INFO.find(name) == mapping_NAME_INFO.end()) return mod_info(-1, -1, -1);
  else return mapping_NAME_INFO.at(name);
}

std::vector<int> TButility::GetUniqueMID(std::vector<int> vec_1, std::vector<int> vec_2) {
  std::vector<int> return_vec;
  std::map<int, int> aMap;

  for (int i = 0; i < vec_1.size(); i++) {
    if (vec_1.at(i) == -1) continue;
    if (aMap.find(vec_1.at(i)) == aMap.end()) {
      return_vec.push_back(vec_1.at(i));
      aMap.insert(std::make_pair(vec_1.at(i), 1));
    }
  }

  for (int i = 0; i < vec_2.size(); i++) {
    if (vec_2.at(i) == -1) continue;
    if (aMap.find(vec_2.at(i)) == aMap.end()) {
      return_vec.push_back(vec_2.at(i));
      aMap.insert(std::make_pair(vec_2.at(i), 1));
    }
  }

  return return_vec;
}

std::vector<int> TButility::GetUniqueMID(std::vector<TBcid> aCID) {
  std::vector<int> return_vec;
  std::map<int, int> aMap;

  for (int i = 0; i < aCID.size(); i++) {
    if (aCID.at(i).mid() == -1) continue;
    if (aMap.find(aCID.at(i).mid()) == aMap.end()) {
      return_vec.push_back(aCID.at(i).mid());
      aMap.insert(std::make_pair(aCID.at(i).mid(), 1));
    }
  }

  return return_vec;
}

std::vector<int> TButility::GetUniqueMID(std::vector<TBcid> aCID_1, std::vector<TBcid> aCID_2) {
  std::vector<int> return_vec;
  std::map<int, int> aMap;

  for (int i = 0; i < aCID_1.size(); i++) {
    if (aCID_1.at(i).mid() == -1) continue;
    if (aMap.find(aCID_1.at(i).mid()) == aMap.end()) {
      return_vec.push_back(aCID_1.at(i).mid());
      aMap.insert(std::make_pair(aCID_1.at(i).mid(), 1));
    }
  }

  for (int i = 0; i < aCID_2.size(); i++) {
    if (aCID_2.at(i).mid() == -1) continue;
    if (aMap.find(aCID_2.at(i).mid()) == aMap.end()) {
      return_vec.push_back(aCID_2.at(i).mid());
      aMap.insert(std::make_pair(aCID_2.at(i).mid(), 1));
    }
  }

  return return_vec;
}
