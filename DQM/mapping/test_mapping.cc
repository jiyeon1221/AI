#include <iostream>
#include <fstream>

#include "TFile.h"
#include "TTree.h"


struct mapping_info
{
	int mid;
	int ch;
	TString name;
	int cases;
	int isCeren;
	int row;
	int column;

	mapping_info(
		int mid_,
		int ch_,
		TString name_,
		int cases_,
		int isCeren_,
		int row_,
		int column_
	) :
	mid(mid_),
	ch(ch_),
	name(name_),
	cases(cases_),
	isCeren(isCeren_),
	row(row_),
	column(column_) {}

	bool operator==(mapping_info a) {
		if (a.mid == mid &&
				a.ch == ch &&
				a.cases == cases &&
				a.name == name &&
				a.isCeren == isCeren &&
				a.row == row &&
				a.column == column)
			return true;
		else
			return false;
	}
};


int test_mapping(std::string inputMap) {

	int mid;
	int ch;
	TString name;
	int cases;
	int isCeren;
	int row;
	int column;

	std::vector<mapping_info> mappingVec;
	std::ifstream in;
	in.open(inputMap + ".csv", std::ios::in);
	while (true) {
		in >> mid >> ch >> name >> cases >> isCeren >> row >> column;
		if (!in.good()) break;

		mappingVec.push_back(mapping_info(mid, ch, name, cases, isCeren, row, column));
	}
	in.close();
	std::cout << mappingVec.size() << std::endl;

	TChain* mapChain = new TChain("mapping");
	mapChain->Add((TString)(inputMap + ".root"));


	TString* name_ = nullptr;
	mapChain->SetBranchAddress("mid", &mid);
	mapChain->SetBranchAddress("ch", &ch);
	mapChain->SetBranchAddress("name", &name_);
	mapChain->SetBranchAddress("cases", &cases);
	mapChain->SetBranchAddress("isCeren", &isCeren);
	mapChain->SetBranchAddress("row", &row);
	mapChain->SetBranchAddress("column", &column);

	for ( int i = 0; i < mapChain->GetEntries(); i++ ) {
		mapChain->GetEntry(i);

		mapping_info aInfo = mapping_info(mid, ch, *name_, cases, isCeren, row, column);

		if( !(aInfo == mappingVec.at(i)) )
			std::cout << i << " is wrong !" << std::endl;
		else
			std::cout << i << " good" << std::endl;

	}


	return 1;
}
