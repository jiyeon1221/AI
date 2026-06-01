#include "TBread.h"
#include "TButility.h"

#include <chrono>
#include <numeric>
#include <vector>
#include <filesystem>
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

// This macro will draw single event waveform (without any PID cuts) from waveform ntuple
// This macro will store waveform plots of pre-shower, module1 tower1 C and S channels in .png format event by event

// How to execute
// On local or batch, run the following command :
// ./TBdrawWave.exe <run number> <max # of events to process>

int main(int argc, char **argv) {
    gStyle->SetOptStat(0);
    gStyle->SetStatFormat("6.6g");
    
    int fRunNum = std::stoi(argv[1]);
    int fMaxEvent = std::stoi(argv[2]);
    int fMaxFile = -1;
    
    std::vector<std::string> channel_names;
    for (int plot_args = 3; plot_args < argc; plot_args++) {
        channel_names.push_back(argv[plot_args]);
    }
    
    fs::path dir("./Overlap");
    if (!(fs::exists(dir))) fs::create_directory(dir);
    
    fs::path dir2("./Overlap/Run_" + std::to_string(fRunNum));
    if (!(fs::exists(dir2))) fs::create_directory(dir2);
    
    TButility util = TButility();
    util.LoadMapping("../mapping/mapping_KEK.root");
    
    std::vector<TBcid> cids;
    std::vector<TH2F *> plots;
    for (int idx = 0; idx < channel_names.size(); idx++)
    {
        plots.push_back(new TH2F((TString)(channel_names.at(idx)), ";bin;ADC", 1024, 0., 1024., 4096, 0., 4096.));
        plots.at(idx)->GetYaxis()->SetRangeUser(0, 4096);
        cids.push_back(util.GetCID(channel_names.at(idx)));
    }
    
    TCanvas *c = new TCanvas("c1", "c1");
    
    TBread<TBwaveform> readerWave = TBread<TBwaveform>(fRunNum, fMaxEvent, fMaxFile, false, "/pnfs/knu.ac.kr/data/cms/store/user/sungwon/2025_KEK_TB_Data", {8, 9, 13});
    
    // Set Maximum event
    if (fMaxEvent == -1 || fMaxEvent > readerWave.GetMaxEvent())
        fMaxEvent = readerWave.GetMaxEvent();
    
    TFile *outFile = new TFile(("./Overlap/Run_" + std::to_string(fRunNum) + "/Run_" + std::to_string(fRunNum) + ".root").c_str(), "RECREATE");
    outFile->cd();
    
    // Starting Evt Loop
    for (int iEvt = 0; iEvt < fMaxEvent; iEvt++) {
        printProgress(iEvt, fMaxEvent);
        TBevt<TBwaveform> aEvent = readerWave.GetAnEvent();
        
        for (int idx = 0; idx < channel_names.size(); idx++) {
            auto single_waveform = aEvent.GetData(cids.at(idx)).waveform();
            for (int bin = 1; bin < 1024; bin++) {
                plots.at(idx)->Fill(bin, single_waveform[bin]);
            }
        }
    }
    
    for (int idx = 0; idx < plots.size(); idx++) {
        outFile->cd();
        c->cd();
        c->RedrawAxis();
        plots.at(idx)->Draw("Hist");
        plots.at(idx)->Write();
        c->SaveAs((TString)("./Overlap/Run_" + std::to_string(fRunNum) + "/Run_" + std::to_string(fRunNum) + "_" + channel_names.at(idx) + ".png"));
        c->Clear();
    }
    
    outFile->Close();
}
