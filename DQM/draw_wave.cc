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


// How to execute
// On local or batch, run the following command :
// ./draw_wave <run number> <max # of events to process> <channel name> <channel name> ...
// Channel name = M1-T3-C, S63, PS, CC1, T1 etc...

int main(int argc, char** argv) {
    gStyle->SetOptStat(0);

    int fRunNum = std::stoi(argv[1]);
    int fMaxEvent = std::stoi(argv[2]);
    int fMaxFile = -1;
    gStyle->SetPalette(kVisibleSpectrum);

    std::vector<std::string> channel_names;
    myColorPalette.clear();
    for (int plot_args = 3; plot_args < argc; plot_args++)
    {
        channel_names.push_back(argv[plot_args]);
        // myColorPalette.push_back(gStyle->GetColorPalette((plot_args - 10) * ((float)gStyle->GetNumberOfColors() / ((float)argc - 10.))));
        myColorPalette.push_back(gStyle->GetColorPalette((plot_args) * ((float)gStyle->GetNumberOfColors() / ((float)argc))));
    }

    fs::path dir("./Waveform");   
    if (!(fs::exists(dir))) fs::create_directory(dir);

    fs::path dir2("./Waveform/Run_" + std::to_string(fRunNum));   
    if (!(fs::exists(dir2))) fs::create_directory(dir2);

    TCanvas* c = new TCanvas("c1", "c1");

    // Here we load mapping information to get cid (channel ID)
    TButility util = TButility();
    util.LoadMapping("../mapping/mapping_KEK.root");
    
    std::vector<TBcid> cids;
    for (int idx = 0; idx < channel_names.size(); idx++) {
        cids.push_back(util.GetCID(channel_names.at(idx)));

        fs::path dir("./Waveform/Run_" + std::to_string(fRunNum) + "/" + channel_names.at(idx));   
        if (!(fs::exists(dir))) fs::create_directory(dir);
    }

    TBread<TBwaveform> readerWave = TBread<TBwaveform>(fRunNum, fMaxEvent, fMaxFile, false, "/pnfs/knu.ac.kr/data/cms/store/user/sungwon/2025_KEK_TB_Data", {8, 9, 13});

    // Set Maximum event
    if (fMaxEvent == -1 || fMaxEvent > readerWave.GetMaxEvent())
        fMaxEvent = readerWave.GetMaxEvent();

    // Exercise 1 : Define cid of both Module 1 Tower 1 Cerenkov channel and Scintillation channel (generic PMT)
    TFile* outFile = new TFile( ( "./Waveform/Run_" + std::to_string(fRunNum) + "/Run_" + std::to_string(fRunNum) + ".root" ).c_str(), "RECREATE");
    outFile->cd();
    
    // Starting Evt Loop
    for (int iEvt = 0; iEvt < fMaxEvent; iEvt++) {
        // Get entry from ntuple TChain
        // Event data can be accessed from TBevt<TBwaveform>* anEvt
        printProgress(iEvt, fMaxEvent);
        TBevt<TBwaveform> aEvent = readerWave.GetAnEvent();

        TLegend* leg = new TLegend(0.75, 0.2, 0.9, 0.4);
        std::vector<TH1F *> plots;
        for (int idx = 0; idx < channel_names.size(); idx++) {
            plots.push_back(new TH1F((TString) (channel_names.at(idx) + "_Evt_" + std::to_string(iEvt) + channel_names.at(idx)), ";bin;ADC", 1000, 0, 1000));
            plots.at(idx)->SetLineColor(myColorPalette.at(idx));
            plots.at(idx)->GetYaxis()->SetRangeUser(3000, 4096);
            // leg->AddEntry(plots.at(idx), (TString)channel_names.at(idx), "l");

        auto single_waveform = aEvent.GetData(cids.at(idx)).waveform();

            for (int bin = 1; bin < 1001; bin++) {
                plots.at(idx)->SetBinContent(bin, single_waveform[bin]);
                plots.at(idx)->SetBinError(bin, 0);
            }
        }

        for (int idx = 0; idx < plots.size(); idx++) {
            outFile->cd();
            c->cd();
            c->RedrawAxis();
            plots.at(idx)->Draw("Hist");
            leg->AddEntry(plots.at(idx), (TString)channel_names.at(idx), "l");
            // if (idx == 0) plots.at(idx)->Draw("Hist");
            // else plots.at(idx)->Draw("Hist&sames");
            leg->Draw("sames");
            plots.at(idx)->Write();
            c->SaveAs( (TString) ( "./Waveform/Run_" + std::to_string(fRunNum) + "/" + channel_names.at(idx) + "/Evt_" + std::to_string(iEvt) + ".png") );
            c->Clear();
            leg->Clear();
        }
    }
    outFile->Close();
}
