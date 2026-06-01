#include <iostream>
#include <fstream>

#include "TFile.h"
#include "TTree.h"


int mapping_generator(std::string inputMap) {

	int mid = 0;
	int ch = 0;
	TString name = "";

	int isCeren = 0;
	int row = 0;
	int column = 0;

	TTree* aTree_DAQ = new TTree("mapping_DAQ", "mapping_DAQ");

	aTree_DAQ->Branch("mid", &mid);
	aTree_DAQ->Branch("ch", &ch);
	aTree_DAQ->Branch("name", &name);

  std::ifstream in;
  in.open(inputMap + ".csv", std::ios::in);
  while (true) {
    in >> mid >> ch >> name;
    if (!in.good()) break;
    aTree_DAQ->Fill();
  }
  in.close();

	TTree* aTree_DQM = new TTree("mapping_DQM", "mapping_DQM");

	aTree_DQM->Branch("name", &name);
	aTree_DQM->Branch("isCeren", &isCeren);
	aTree_DQM->Branch("row", &row);
	aTree_DQM->Branch("column", &column);

  in.open(inputMap + "_DQM.csv", std::ios::in);
  while (true) {
    in >> name >> isCeren >> row >> column;
    if (!in.good()) break;
    aTree_DQM->Fill();
  }
  in.close();

  TFile* aFile = new TFile((TString)(inputMap + ".root"), "RECREATE");
  aTree_DAQ->Write();
  aTree_DQM->Write();
  aFile->Close();



  return 1;
}