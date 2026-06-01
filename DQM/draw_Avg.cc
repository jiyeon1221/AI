#include "TBread.h"
#include "TButility.h"

#include "stdio.h"
#include "stdlib.h"
#include "string.h"
#include <chrono>
#include <filesystem>
#include <iostream>
#include <numeric>
#include <vector>

#include "TCanvas.h"
#include "TFile.h"
#include "TH1.h"
#include "TH2.h"
#include "TLegend.h"
#include "TROOT.h"
#include "TStyle.h"

#include "function.h"

namespace fs = std::filesystem;

int main(int argc, char *argv[]) {
    // Set styles
    // For avg time struc, do not need stat box
    gStyle->SetPalette(kVisibleSpectrum);
    gStyle->SetOptStat(0);
    gStyle->SetStatFormat("6.6g");
    
    // setup for prompt analysis
    int fRunNum = std::stoi(argv[1]);
    int fMaxEvent = std::stoi(argv[2]);
    int fMaxFile = -1;    
    std::vector<std::string> channel_names;
    std::string full_channel_name = "";
    for (int plot_args = 3; plot_args < argc; plot_args++) {
        channel_names.push_back(argv[plot_args]);
        full_channel_name += std::string(argv[plot_args]) + "_";
    }
    full_channel_name = full_channel_name.substr(0, full_channel_name.size() - 1);
    
    // Create output directory
    fs::path dir("./Avg");
    if (!(fs::exists(dir))) fs::create_directory(dir);
    fs::path dir2("./Avg/Run_" + std::to_string(fRunNum));
    if (!(fs::exists(dir2))) fs::create_directory(dir2);
    
    // Load mapping
    TButility util = TButility();
    util.LoadMapping("../mapping/mapping_KEK.root");
    
    std::vector<TBcid> cids;
    std::vector<TH1F *> plots;
    for (int idx = 0; idx < channel_names.size(); idx++) {
        plots.push_back(new TH1F((TString)channel_names.at(idx), ";bin;ADC", 1000, 0, 1000));
        cids.push_back(util.GetCID(channel_names.at(idx)));
    }
        
    // MID: 3-7: PMT modules, MID 9: LC, MID 10: Aux(CC1, CC2, PS, TC, MC), MID 12: Triggers (T1, T2, T1NIM, T2NIM, Coin), MID 14-17: MCP micro, MID 18: DWC
    TBread<TBwaveform> readerWave = TBread<TBwaveform>(fRunNum, fMaxEvent, fMaxFile, false, "/pnfs/knu.ac.kr/data/cms/store/user/sungwon/2025_KEK_TB_Data", {8, 9, 13});
    
    // Set Maximum event
    if (fMaxEvent == -1 || fMaxEvent > readerWave.GetMaxEvent())
    fMaxEvent = readerWave.GetMaxEvent();
    
    // Start event loop
    for (int i = 0; i < fMaxEvent; i++) {
        printProgress(i, fMaxEvent);
        // Load event
        TBevt<TBwaveform> aEvent = readerWave.GetAnEvent();
        // Get waveform of certain channel we want to use
        // filling plots
        for (int idx = 0; idx < plots.size(); idx++) {
            auto single_waveform = aEvent.GetData(cids.at(idx)).waveform();
            
            std::vector<float> avgTimeStruc = GetAvg(single_waveform, fMaxEvent);
            for (int bin = 1; bin < 1001; bin++) {
                plots.at(idx)->Fill(bin, avgTimeStruc.at(bin));
            }
        }
    } // end of event loop

    TCanvas *c = new TCanvas("c", "c", 1000, 800);
    c->cd();
        
    TLegend *leg = new TLegend(0.75, 0.2, 0.9, 0.4);

    for (int idx = 0; idx < plots.size(); idx++) {
        plots.at(idx)->SetLineWidth(2);
        plots.at(idx)->SetLineColor(myColorPalette.at(idx));
        plots.at(idx)->GetYaxis()->SetRangeUser(1000, 4096);
        
        c->cd();
        if (idx == 0) plots.at(idx)->Draw("Hist");
        else plots.at(idx)->Draw("Hist & sames");
        
        leg->AddEntry(plots.at(idx), channel_names.at(idx).c_str(), "l");
        c->Update();
    }
    
    leg->Draw("sames");    
    c->Update();
    c->SaveAs((TString)("./Avg/Run_" + std::to_string(fRunNum) + "/" + full_channel_name + ".png"));
    
    return 0;
}