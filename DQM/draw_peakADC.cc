#include "TBread.h"
#include "TButility.h"

#include <filesystem>
#include <chrono>
#include <numeric>
#include <vector>
#include "stdlib.h"
#include "stdio.h"
#include "string.h"

#include "TCanvas.h"
#include "TH1.h"
#include "TH2.h"
#include "TFile.h"
#include "TApplication.h"
#include "TRootCanvas.h"
#include "TPaveStats.h"

#include "TLegend.h"
#include "TLatex.h"
#include "TColor.h"

#include "function.h"

namespace fs = std::filesystem;

int main(int argc, char *argv[]) {
	gStyle->SetPalette(kVisibleSpectrum);
	gStyle->SetStatFormat("6.6g");
  
	// setup for prompt analysis
	int fRunNum = std::stoi(argv[1]);
	int fMaxEvent = std::stoi(argv[2]);
	int fStartBin = std::stoi(argv[3]);
	int fEndBin = std::stoi(argv[4]);
	int fMaxFile = -1;

    std::vector<std::string> channel_names;
    std::string full_channel_name = "";
    myColorPalette.clear();
	for (int plot_args = 5; plot_args < argc; plot_args++)
	{
		channel_names.push_back(argv[plot_args]);
		full_channel_name += std::string(argv[plot_args]) + "_";
        myColorPalette.push_back(gStyle->GetColorPalette( (plot_args - 10) * ((float)gStyle->GetNumberOfColors() / ((float)argc - 10.))));
	}
    full_channel_name = full_channel_name.substr(0, full_channel_name.size() - 1);

	fs::path dir("./PeakADC");   
	if (!(fs::exists(dir))) fs::create_directory(dir);
	fs::path dir2("./PeakADC/Run_" + std::to_string(fRunNum));
	if (!(fs::exists(dir2))) fs::create_directory(dir2);

	// Cut values
	float cut_CC1 = 200.;
	float cut_CC2 = 200.;
	float cut_DWC = 1.5;

	// Integral range
	// int start_bin = fStartBin;
	// int end_bin = fEndBin;
	// height for text legend
	TLatex* text = new TLatex();
	text->SetTextSize(0.025);  
	float height = 0.87;

	// initialize the utility class
	TButility util = TButility();
	util.LoadMapping("../mapping/mapping_KEK.root");
	
	std::vector<TBcid> cids;
	std::vector<TH1F *> plots;
	for (int idx = 0; idx < channel_names.size(); idx++) {
		plots.push_back(new TH1F((TString)channel_names.at(idx), ";peakADC;nEvents", 4096, 0, 4096));
		cids.push_back(util.GetCID(channel_names.at(idx)));
	}

    TBread<TBwaveform> readerWave = TBread<TBwaveform>(fRunNum, fMaxEvent, fMaxFile, false, "/pnfs/knu.ac.kr/data/cms/store/user/sungwon/2025_KEK_TB_Data", {8, 9, 13});

	// Set Maximum event
    if (fMaxEvent == -1 || fMaxEvent > readerWave.GetMaxEvent())
    fMaxEvent = readerWave.GetMaxEvent();

	TCanvas *c = new TCanvas("c", "c", 1000, 800);
	c->cd();

	TLegend* leg = new TLegend(0.75, 0.2, 0.9, 0.4);

    TFile* outFile = new TFile( ( "./PeakADC/Run_" + std::to_string(fRunNum) + "/Run_" + std::to_string(fRunNum) + ".root" ).c_str(), "RECREATE");
    outFile->cd();

    // Starting Evt Loop
    for (int iEvt = 0; iEvt < fMaxEvent; iEvt++) {
		printProgress(iEvt, fMaxEvent);

		// Load event
		TBevt<TBwaveform> aEvent = readerWave.GetAnEvent();

		// filling plots
		for (int idx = 0; idx < plots.size(); idx++)
		{
			auto single_waveform = aEvent.GetData(cids.at(idx)).waveform();

			float PeakADC = GetPeak(single_waveform, fStartBin, fEndBin);
			plots.at(idx)->Fill(PeakADC);
		}
  	} //end of event loop
	
	outFile->cd();
	for (int idx = 0; idx < plots.size(); idx++) {
		plots.at(idx)->Draw("hist");
		plots.at(idx)->Write();
	}
	outFile->Close();

	return 0;
}