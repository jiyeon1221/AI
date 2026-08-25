#include "TBplotengine.h"
#include "GuiTypes.h"
#include "TSystem.h"
#include "TStyle.h"
#include "TPaveStats.h"

#include <cstdio>
#include <climits>

TBplotengine::TBplotengine(const YAML::Node fConfig_, int fRunNum_, bool fLive_, bool fDraw_, TButility fUtility_)
: fConfig(fConfig_), fRunNum(fRunNum_), fLive(fLive_), fDraw(fDraw_), fUtility(fUtility_), fCaseName(""), fAuxCut(false)
{}

void TBplotengine::init() {

  fIsFirst = true;
  fUsingAUX = false;
  gStyle->SetPalette(kRainBow);

  std::vector<int> fColorVec = {
    TColor::GetColor("#5790fc"),
    TColor::GetColor("#f89c20"),
    TColor::GetColor("#009E73"),
    TColor::GetColor("#e42536"),
    TColor::GetColor("#F0E442"),
    TColor::GetColor("#7a21dd"),
    TColor::GetColor("#964a8b"),
    TColor::GetColor("#661100"),
    TColor::GetColor("#9c9ca1"),
    TColor::GetColor("#44AA99"),
  };

  if (fCaseName == "single") {

    if (fCalcInfo == TBplotengine::CalcInfo::kAvgTimeStruc) {
      fLeg = new TLegend(0.7, 0.2, 0.9, 0.5);
     	fLeg->SetFillStyle(0);
     	fLeg->SetBorderSize(0);
     	fLeg->SetTextFont(42);
    }


    for (int i = 0; i < fNametoPlot.size(); i++) {
      std::string aName = fNametoPlot.at(i);
      TBcid aCID = fUtility.GetCID(aName);
      fCIDtoPlot_Ceren.push_back(aCID);

      TButility::mod_info aInfo = fUtility.GetInfo(aCID);

      if (fCalcInfo == TBplotengine::CalcInfo::kIntADC || fCalcInfo == TBplotengine::CalcInfo::kPeakADC) {
        std::vector<int> interval = fConfig[aName].as<std::vector<int>>();
        fPlotter_Ceren.push_back(TBplotengine::PlotInfo(aCID, aName, aInfo, interval.at(0), interval.at(1)));

        if (fCalcInfo == TBplotengine::CalcInfo::kIntADC) {
         if (aName.find("LC") != std::string::npos) fPlotter_Ceren.at(i).SetPlot(new TH1D((TString)(aName), ";IntADC;nEvents", 1200, -10000., 50000.));
         else fPlotter_Ceren.at(i).SetPlot(new TH1D((TString)(aName), ";IntADC;nEvents", 440, -30000., 300000.));
        }

        if (fCalcInfo == TBplotengine::CalcInfo::kPeakADC)
          fPlotter_Ceren.at(i).SetPlot(new TH1D((TString)(aName), ";PeakADC;nEvents", 1152, -512., 4096.));

        fPlotter_Ceren.at(i).hist1D->SetLineColor(fColorVec.at(i));
        fPlotter_Ceren.at(i).hist1D->SetLineWidth(2);

      } else if (fCalcInfo == TBplotengine::CalcInfo::kAvgTimeStruc) {
        fPlotter_Ceren.push_back(TBplotengine::PlotInfo(aCID, aName, aInfo, 0, 0));
        fPlotter_Ceren.at(i).SetPlot(new TH1D((TString)(aName), ";Bin;ADC", 1000, 0.5, 1000.5));
        fPlotter_Ceren.at(i).hist1D->SetLineColor(fColorVec.at(i));
        fPlotter_Ceren.at(i).hist1D->SetLineWidth(2);
        fPlotter_Ceren.at(i).hist1D->SetStats(0);

      } else if (fCalcInfo == TBplotengine::CalcInfo::kOverlay) {
        fPlotter_Ceren.push_back(TBplotengine::PlotInfo(aCID, aName, aInfo, 0, 0));
        fPlotter_Ceren.at(i).SetPlot(new TH2D((TString)(aName), (TString)"Run " + std::to_string(fRunNum) + ";Bin;ADC", 1024, 0., 1024., 4096, 0., 4096.));
        fPlotter_Ceren.at(i).hist2D->SetStats(0);

      } else {
        fPlotter_Ceren.push_back(TBplotengine::PlotInfo(aCID, aName, aInfo));
      }
    }

    if (fCalcInfo == TBplotengine::CalcInfo::kAvgTimeStruc) {
      fMainFrame = new TH1D("frame", (TString)"Run " + std::to_string(fRunNum) + ";Bin;ADC", 1000, 0.5, 1000.5);
      fMainFrame->SetStats(0);
    }

    if (fCalcInfo == TBplotengine::CalcInfo::kIntADC) {
      fMainFrame = new TH1D("frame", (TString)"Run " + std::to_string(fRunNum) + ";IntADC;nEvents", 440, -30000., 300000.);
      fMainFrame->SetStats(0);
    }

    if (fCalcInfo == TBplotengine::CalcInfo::kPeakADC) {
      fMainFrame = new TH1D("frame", (TString)"Run " + std::to_string(fRunNum) + ";PeakADC;nEvents", 288, -512., 4096.);
      fMainFrame->SetStats(0);
    }

    fCanvas = new TCanvas("fCanvasPlot", "fCanvasPlot", 1400, 1400);

    Draw();
  } else if (fCaseName == "full") {

    fCanvasFull.push_back(new TCanvas("fCanvasHeatmap", "fCanvasHeatmap", 2700, 1000));
    fCanvasFull.at(0)->Divide(2, 1);

    auto tPadLeft = fCanvasFull.at(0)->cd(1);
    tPadLeft->SetRightMargin(0.13);

    auto tPadRight = fCanvasFull.at(0)->cd(2);
    tPadRight->SetRightMargin(0.13);

    // 매핑에서 찾은 타워마다 캔버스를 만든다.
    init_Generic();
  } else if (fCaseName == "module") {

    // 매핑 배치에 따라 타워별 C/S 분포 격자를 만든다.
    init_module();
  } else if (fCaseName == "heatmap") {

    // heatmap은 MCPPMT의 C1~C64와 S1~S64를 지원한다.
    if (fModule != "MCPPMT") {
      std::cerr << "[TBplotengine] --type heatmap currently supports only "
                << "--module MCPPMT (got --module '" << fModule << "'). "
                << "Skipping init." << std::endl;
      return;
    }

    fCanvasFull.push_back(new TCanvas("fCanvasMCPPMT", "fCanvasMCPPMT", 2700, 1000));
    fCanvasFull.at(0)->Divide(2, 1);

    auto tPadLeft = fCanvasFull.at(0)->cd(1);
    tPadLeft->SetRightMargin(0.13);

    auto tPadRight = fCanvasFull.at(0)->cd(2);
    tPadRight->SetRightMargin(0.13);

    init_MCPPMT();
  }
}


void TBplotengine::init_Generic() {

  // 매핑의 -C/-S 채널과 행·열 좌표에서 타워 격자를 구성한다.
  std::vector<std::string> cerenNames, scintNames;
  int maxRow = 0, maxCol = 0;

  for (const auto& kv : fUtility.GetNameInfo()) {
    const std::string name = std::string(kv.first.Data());
    const auto& info = kv.second;
    if (info.row <= 0 || info.col <= 0) continue;
    if (name.size() < 2) continue;
    const std::string suffix = name.substr(name.size() - 2);
    if (suffix == "-C" && info.isCeren == 1) {
      cerenNames.push_back(name);
      maxRow = std::max(maxRow, info.row);
      maxCol = std::max(maxCol, info.col);
    } else if (suffix == "-S" && info.isCeren == 0) {
      scintNames.push_back(name);
      maxRow = std::max(maxRow, info.row);
      maxCol = std::max(maxCol, info.col);
    }
  }

  // 이름순으로 정렬해 C와 S 채널 인덱스를 맞춘다.
  std::sort(cerenNames.begin(), cerenNames.end());
  std::sort(scintNames.begin(), scintNames.end());

  if (cerenNames.empty() && scintNames.empty()) {
    std::cerr << "[TBplotengine] init_Generic: no tower-like channels found in "
              << "mapping (looked for names ending in '-C' or '-S' with valid "
              << "row/col). The CERENKOV/SCINTILLATION heatmaps will be empty."
              << std::endl;
  }
  if (cerenNames.size() != scintNames.size()) {
    std::cerr << "[TBplotengine] init_Generic: Cherenkov and Scintillator "
              << "tower counts differ in the mapping ("
              << cerenNames.size() << " vs " << scintNames.size() << "). "
              << "Per-tower 1D canvases will use min(C, S)." << std::endl;
  }

  for (size_t i = 0; i < cerenNames.size(); ++i) {
    const std::string& aCName = cerenNames[i];
    TBcid aCCID = fUtility.GetCID(aCName);
    TButility::mod_info aCInfo = fUtility.GetInfo(aCName);

    fCIDtoPlot_Ceren.push_back(aCCID);

    std::vector<int> intervalC = fConfig[aCName].as<std::vector<int>>();
    fPlotter_Ceren.push_back(TBplotengine::PlotInfo(aCCID, aCName, aCInfo, intervalC.at(0), intervalC.at(1)));

    if (fCalcInfo == TBplotengine::CalcInfo::kIntADC)
      fPlotter_Ceren.at(i).SetPlot(new TH1D((TString)(aCName), ";IntADC;nEvents", 440, -30000., 300000.));

    if (fCalcInfo == TBplotengine::CalcInfo::kPeakADC)
      fPlotter_Ceren.at(i).SetPlot(new TH1D((TString)(aCName), ";PeakADC;nEvents", 288, -512., 4096.));

    fPlotter_Ceren.at(i).hist1D->SetLineWidth(2);
    fPlotter_Ceren.at(i).hist1D->SetLineColor(kBlue);
  }

  for (size_t i = 0; i < scintNames.size(); ++i) {
    const std::string& aSName = scintNames[i];
    TBcid aSCID = fUtility.GetCID(aSName);
    TButility::mod_info aSInfo = fUtility.GetInfo(aSName);

    fCIDtoPlot_Scint.push_back(aSCID);

    std::vector<int> intervalS = fConfig[aSName].as<std::vector<int>>();
    fPlotter_Scint.push_back(TBplotengine::PlotInfo(aSCID, aSName, aSInfo, intervalS.at(0), intervalS.at(1)));

    if (fCalcInfo == TBplotengine::CalcInfo::kIntADC)
      fPlotter_Scint.at(i).SetPlot(new TH1D((TString)(aSName), ";IntADC;nEvents", 440, -30000., 300000.));

    if (fCalcInfo == TBplotengine::CalcInfo::kPeakADC)
      fPlotter_Scint.at(i).SetPlot(new TH1D((TString)(aSName), ";PeakADC;nEvents", 288, -512., 4096.));

    fPlotter_Scint.at(i).hist1D->SetLineWidth(2);
    fPlotter_Scint.at(i).hist1D->SetLineColor(kRed);
  }

  // 매핑 범위로 정사각형 heatmap 크기를 정한다.
  const int gridX = std::max(1, maxRow);
  const int gridY = std::max(1, maxCol);

  f2DHistCeren = new TH2D("CERENKOV", "CERENKOV;;", gridX, 0.5, gridX + 0.5, gridY, 0.5, gridY + 0.5);
  f2DHistCeren->SetStats(0);

  f2DHistScint = new TH2D("SCINTILLATION", "SCINTILLATION;;", gridX, 0.5, gridX + 0.5, gridY, 0.5, gridY + 0.5);
  f2DHistScint->SetStats(0);

  for (int i = 1; i <= gridX; ++i) {
    f2DHistCeren->GetXaxis()->SetBinLabel(i, std::to_string(i).c_str());
    f2DHistScint->GetXaxis()->SetBinLabel(i, std::to_string(i).c_str());
  }
  for (int i = 1; i <= gridY; ++i) {
    f2DHistCeren->GetYaxis()->SetBinLabel(i, std::to_string(i).c_str());
    f2DHistScint->GetYaxis()->SetBinLabel(i, std::to_string(i).c_str());
  }

  // C/S 양쪽에 존재하는 타워만 1D 캔버스로 만든다.
  const size_t nTowers = std::min(fPlotter_Ceren.size(), fPlotter_Scint.size());
  for (size_t i = 0; i < nTowers; ++i) {
    std::string aCanvasName = "fCanvas_Tower" + std::to_string(i + 1);
    fCanvasFull.push_back(new TCanvas((TString)aCanvasName, (TString)aCanvasName, 1400, 700));
    fCanvasFull.back()->Divide(2, 1);
  }

  Draw();
}


void TBplotengine::init_module() {

  // module 유형은 선택한 접두사의 타워별 1D 분포 격자를 만든다.

  const bool hasFilter = !fModule.empty();
  const std::string filterPrefix = hasFilter ? fModule + "-" : "";

  std::vector<std::string> cerenNames, scintNames;
  int minRow = INT_MAX, minCol = INT_MAX;
  int maxRow = 0, maxCol = 0;

  for (const auto& kv : fUtility.GetNameInfo()) {
    const std::string name = std::string(kv.first.Data());
    const auto& info = kv.second;
    if (info.row <= 0 || info.col <= 0) continue;
    if (name.size() < 2) continue;
    if (hasFilter && name.compare(0, filterPrefix.size(), filterPrefix) != 0) continue;
    const std::string suffix = name.substr(name.size() - 2);
    if (suffix == "-C" && info.isCeren == 1) {
      cerenNames.push_back(name);
    } else if (suffix == "-S" && info.isCeren == 0) {
      scintNames.push_back(name);
    } else {
      continue;
    }
    minRow = std::min(minRow, info.row);
    minCol = std::min(minCol, info.col);
    maxRow = std::max(maxRow, info.row);
    maxCol = std::max(maxCol, info.col);
  }

  std::sort(cerenNames.begin(), cerenNames.end());
  std::sort(scintNames.begin(), scintNames.end());

  if (cerenNames.empty() && scintNames.empty()) {
    std::cerr << "[TBplotengine] init_module: no tower channels found"
              << (hasFilter ? (" for prefix '" + fModule + "-'.") : ".")
              << " The module-view canvas will be empty." << std::endl;
    fGridX_module = 1;
    fGridY_module = 1;
    fCanvas = new TCanvas("fCanvasModule", "fCanvasModule", 1400, 1400);
    Draw();
    return;
  }

  // 절대 매핑 좌표를 선택 모듈의 로컬 격자로 변환한다.
  fGridX_module = maxRow - minRow + 1;
  fGridY_module = maxCol - minCol + 1;
  const int rowOffset = minRow - 1;
  const int colOffset = minCol - 1;

  // ROOT의 왼쪽 위 기준 pad 번호로 좌표를 변환한다.
  fCanvas = new TCanvas("fCanvasModule", "fCanvasModule",
                        std::max(700, 400 * fGridX_module),
                        std::max(700, 400 * fGridY_module));
  fCanvas->Divide(fGridX_module, fGridY_module);

  for (size_t i = 0; i < cerenNames.size(); ++i) {
    const std::string& aCName = cerenNames[i];
    TBcid aCCID = fUtility.GetCID(aCName);
    TButility::mod_info aCInfo = fUtility.GetInfo(aCName);
    // 그리기 단계에서 사용할 로컬 좌표를 저장한다.
    aCInfo.row -= rowOffset;
    aCInfo.col -= colOffset;

    fCIDtoPlot_Ceren.push_back(aCCID);

    std::vector<int> intervalC = fConfig[aCName].as<std::vector<int>>();
    fPlotter_Ceren.push_back(TBplotengine::PlotInfo(aCCID, aCName, aCInfo, intervalC.at(0), intervalC.at(1)));

    if (fCalcInfo == TBplotengine::CalcInfo::kIntADC)
      fPlotter_Ceren.back().SetPlot(new TH1D((TString)(aCName), (TString)(aCName + ";IntADC;nEvents"), 440, -30000., 300000.));

    if (fCalcInfo == TBplotengine::CalcInfo::kPeakADC)
      fPlotter_Ceren.back().SetPlot(new TH1D((TString)(aCName), (TString)(aCName + ";PeakADC;nEvents"), 288, -512., 4096.));

    fPlotter_Ceren.back().hist1D->SetLineWidth(2);
    fPlotter_Ceren.back().hist1D->SetLineColor(kBlue);
  }

  for (size_t i = 0; i < scintNames.size(); ++i) {
    const std::string& aSName = scintNames[i];
    TBcid aSCID = fUtility.GetCID(aSName);
    TButility::mod_info aSInfo = fUtility.GetInfo(aSName);
    aSInfo.row -= rowOffset;
    aSInfo.col -= colOffset;

    fCIDtoPlot_Scint.push_back(aSCID);

    std::vector<int> intervalS = fConfig[aSName].as<std::vector<int>>();
    fPlotter_Scint.push_back(TBplotengine::PlotInfo(aSCID, aSName, aSInfo, intervalS.at(0), intervalS.at(1)));

    if (fCalcInfo == TBplotengine::CalcInfo::kIntADC)
      fPlotter_Scint.back().SetPlot(new TH1D((TString)(aSName), (TString)(aSName + ";IntADC;nEvents"), 440, -30000., 300000.));

    if (fCalcInfo == TBplotengine::CalcInfo::kPeakADC)
      fPlotter_Scint.back().SetPlot(new TH1D((TString)(aSName), (TString)(aSName + ";PeakADC;nEvents"), 288, -512., 4096.));

    fPlotter_Scint.back().hist1D->SetLineWidth(2);
    fPlotter_Scint.back().hist1D->SetLineColor(kRed);
  }

  Draw();
}


void TBplotengine::init_MCPPMT() {

  // MCPPMT 채널명은 C1~C64와 S1~S64이다.
  for (int i = 1; i <= 64; ++i) {
    const std::string aCName = "C" + std::to_string(i);
    const TBcid aCCID = fUtility.GetCID(aCName);
    const TButility::mod_info aCInfo = fUtility.GetInfo(aCName);

    fCIDtoPlot_Ceren.push_back(aCCID);

    const std::vector<int> intervalC = fConfig[aCName].as<std::vector<int>>();
    fPlotter_Ceren.push_back(TBplotengine::PlotInfo(aCCID, aCName, aCInfo, intervalC.at(0), intervalC.at(1)));

    if (fCalcInfo == TBplotengine::CalcInfo::kIntADC)
      fPlotter_Ceren.back().SetPlot(new TH1D((TString)aCName, ";IntADC;nEvents", 440, -30000., 300000.));

    if (fCalcInfo == TBplotengine::CalcInfo::kPeakADC)
      fPlotter_Ceren.back().SetPlot(new TH1D((TString)aCName, ";PeakADC;nEvents", 288, -512., 4096.));

    fPlotter_Ceren.back().hist1D->SetLineWidth(2);
    fPlotter_Ceren.back().hist1D->SetLineColor(kBlue);

    const std::string aSName = "S" + std::to_string(i);
    const TBcid aSCID = fUtility.GetCID(aSName);
    const TButility::mod_info aSInfo = fUtility.GetInfo(aSName);

    fCIDtoPlot_Scint.push_back(aSCID);

    const std::vector<int> intervalS = fConfig[aSName].as<std::vector<int>>();
    fPlotter_Scint.push_back(TBplotengine::PlotInfo(aSCID, aSName, aSInfo, intervalS.at(0), intervalS.at(1)));

    if (fCalcInfo == TBplotengine::CalcInfo::kIntADC)
      fPlotter_Scint.back().SetPlot(new TH1D((TString)aSName, ";IntADC;nEvents", 440, -30000., 300000.));

    if (fCalcInfo == TBplotengine::CalcInfo::kPeakADC)
      fPlotter_Scint.back().SetPlot(new TH1D((TString)aSName, ";PeakADC;nEvents", 288, -512., 4096.));

    fPlotter_Scint.back().hist1D->SetLineWidth(2);
    fPlotter_Scint.back().hist1D->SetLineColor(kRed);
  }

  // 매핑의 열·행 좌표로 8×8 heatmap을 만든다.
  f2DHistCeren = new TH2D("MCPPMT_C", "MCPPMT C;column;row", 8, 0.5, 8.5, 8, 0.5, 8.5);
  f2DHistCeren->SetStats(0);

  f2DHistScint = new TH2D("MCPPMT_S", "MCPPMT S;column;row", 8, 0.5, 8.5, 8, 0.5, 8.5);
  f2DHistScint->SetStats(0);

  for (int i = 1; i <= 8; ++i) {
    f2DHistCeren->GetXaxis()->SetBinLabel(i, std::to_string(i).c_str());
    f2DHistCeren->GetYaxis()->SetBinLabel(i, std::to_string(i).c_str());
    f2DHistScint->GetXaxis()->SetBinLabel(i, std::to_string(i).c_str());
    f2DHistScint->GetYaxis()->SetBinLabel(i, std::to_string(i).c_str());
  }

  Draw();
}


double TBplotengine::GetPeakADC(std::vector<short> waveform, int xInit, int xFin, int pedBins) {
  // 채널별 설정 구간의 파형 평균을 pedestal로 사용한다.
  if (pedBins <= 0 || static_cast<size_t>(pedBins) >= waveform.size())
    pedBins = 100;

  double ped = 0;
  for (int i = 1; i <= pedBins; i++)
    ped += (double)waveform.at(i) / (double)pedBins;

  std::vector<double> pedCorWave;
  for (int i = xInit; i < xFin; i++)
    pedCorWave.push_back(ped - (double)waveform.at(i));

  return *std::max_element(pedCorWave.begin(), pedCorWave.end());
}

double TBplotengine::GetIntADC(std::vector<short> waveform, int xInit, int xFin, int pedBins) {

  if (pedBins <= 0 || static_cast<size_t>(pedBins) >= waveform.size())
    pedBins = 100;

  double ped = 0;
  for (int i = 1; i <= pedBins; i++)
    ped += (double)waveform.at(i) / (double)pedBins;

  double intADC_ = 0;
  for (int i = xInit; i < xFin; i++)
    intADC_ += ped - (double)waveform.at(i);

  return intADC_;
}

void TBplotengine::PrintInfo() {

}

void TBplotengine::Fill(TBevt<TBwaveform> anEvent) {

  if (fCaseName == "single") {
    if (fCalcInfo == TBplotengine::CalcInfo::kIntADC || fCalcInfo == TBplotengine::CalcInfo::kPeakADC) {
      for (int i = 0; i < fPlotter_Ceren.size(); i++) {
        double value = GetValue(anEvent.GetData(fPlotter_Ceren.at(i).cid).waveform(), fPlotter_Ceren.at(i).xInit, fPlotter_Ceren.at(i).xFin, fPlotter_Ceren.at(i).name);
        fPlotter_Ceren.at(i).hist1D->Fill(value);
      }
    } else if (fCalcInfo == TBplotengine::CalcInfo::kAvgTimeStruc) {
      for (int i = 0; i < fPlotter_Ceren.size(); i++) {
        auto tWave = anEvent.GetData(fPlotter_Ceren.at(i).cid).waveform();
        for (int j = 1; j <= 1000; j++) {
          fPlotter_Ceren.at(i).hist1D->Fill(j, tWave.at(j));
        }
        fPlotter_Ceren.at(i).xInit++;
      }
    } else if (fCalcInfo == TBplotengine::CalcInfo::kOverlay) {
      for (int i = 0; i < fPlotter_Ceren.size(); i++) {
        auto tWave = anEvent.GetData(fPlotter_Ceren.at(i).cid).waveform();
        for (int j = 0; j < tWave.size(); j++) {
          fPlotter_Ceren.at(i).hist2D->Fill(j, tWave.at(j));
        }
      }
    }

  } else if (fCaseName == "full" || fCaseName == "heatmap") {
    // 채널별 평균을 매핑 좌표의 heatmap bin에 반영한다.

    for (int i = 0; i < fPlotter_Ceren.size(); i++) {
      double value = GetValue(anEvent.GetData(fPlotter_Ceren.at(i).cid).waveform(), fPlotter_Ceren.at(i).xInit, fPlotter_Ceren.at(i).xFin, fPlotter_Ceren.at(i).name);
      fPlotter_Ceren.at(i).hist1D->Fill(value);

      if (fPlotter_Ceren.at(i).info.row > 0 && fPlotter_Ceren.at(i).info.col > 0) {
        f2DHistCeren->Fill(fPlotter_Ceren.at(i).info.col, fPlotter_Ceren.at(i).info.row, value);
      }
    }

    for (int i = 0; i < fPlotter_Scint.size(); i++) {
      double value = GetValue(anEvent.GetData(fPlotter_Scint.at(i).cid).waveform(), fPlotter_Scint.at(i).xInit, fPlotter_Scint.at(i).xFin, fPlotter_Scint.at(i).name);
      fPlotter_Scint.at(i).hist1D->Fill(value);

      if (fPlotter_Scint.at(i).info.row > 0 && fPlotter_Scint.at(i).info.col > 0) {
        f2DHistScint->Fill(fPlotter_Scint.at(i).info.col, fPlotter_Scint.at(i).info.row, value);
      }
    }
  } else if (fCaseName == "module") {
    // module 유형은 타워별 1D 분포만 채운다.
    for (size_t i = 0; i < fPlotter_Ceren.size(); ++i) {
      const double value = GetValue(anEvent.GetData(fPlotter_Ceren.at(i).cid).waveform(),
                                    fPlotter_Ceren.at(i).xInit, fPlotter_Ceren.at(i).xFin,
                                    fPlotter_Ceren.at(i).name);
      fPlotter_Ceren.at(i).hist1D->Fill(value);
    }
    for (size_t i = 0; i < fPlotter_Scint.size(); ++i) {
      const double value = GetValue(anEvent.GetData(fPlotter_Scint.at(i).cid).waveform(),
                                    fPlotter_Scint.at(i).xInit, fPlotter_Scint.at(i).xFin,
                                    fPlotter_Scint.at(i).name);
      fPlotter_Scint.at(i).hist1D->Fill(value);
    }
  }
}

void TBplotengine::Draw() {

  if (fCalcInfo == TBplotengine::CalcInfo::kAvgTimeStruc) {
    for (int i = 0; i < fPlotter_Ceren.size(); i++)
      fLeg->AddEntry(fPlotter_Ceren.at(i).hist1D, fPlotter_Ceren.at(i).name.c_str(), "l");

  }

  if (fCaseName == "single") {
    fCanvas->cd();

    if (fCalcInfo == TBplotengine::CalcInfo::kOverlay) {
      fPlotter_Ceren.at(0).hist2D->Draw("colz");

    } else {
      fMainFrame->Draw();
      for (int i = 0; i < fPlotter_Ceren.size(); i++)
        fPlotter_Ceren.at(i).hist1D->Draw("sames");

      if (fCalcInfo == TBplotengine::CalcInfo::kAvgTimeStruc)
        fLeg->Draw("same");
    }

  } else if (fCaseName == "full" || fCaseName == "heatmap") {

    fCanvasFull.at(0)->cd(1);
    f2DHistCeren->Draw("colz text");

    fCanvasFull.at(0)->cd(2);
    f2DHistScint->Draw("colz text");

    // full 유형만 타워별 전용 1D 캔버스를 그린다.
    if (fCaseName == "full") {
      const size_t nTowerCanvas = fCanvasFull.size() > 1 ? fCanvasFull.size() - 1 : 0;
      const size_t nTowers = std::min({fPlotter_Ceren.size(), fPlotter_Scint.size(), nTowerCanvas});
      for (size_t idx = 0; idx < nTowers; ++idx) {
        const size_t iTower = idx + 1;

        fCanvasFull.at(iTower)->cd(1);
        fPlotter_Ceren.at(idx).hist1D->Draw("Hist");

        fCanvasFull.at(iTower)->cd(2);
        fPlotter_Scint.at(idx).hist1D->Draw("Hist");
      }
    }
  } else if (fCaseName == "module") {
    // 로컬 행·열 좌표에서 module 캔버스의 pad 번호를 계산한다.
    for (size_t i = 0; i < fPlotter_Ceren.size(); ++i) {
      const auto& info = fPlotter_Ceren.at(i).info;
      if (info.row < 1 || info.row > fGridX_module ||
          info.col < 1 || info.col > fGridY_module) continue;
      const int pad = (fGridY_module - info.col) * fGridX_module + info.row;
      fCanvas->cd(pad);
      fPlotter_Ceren.at(i).hist1D->Draw("Hist");
    }
    for (size_t i = 0; i < fPlotter_Scint.size(); ++i) {
      const auto& info = fPlotter_Scint.at(i).info;
      if (info.row < 1 || info.row > fGridX_module ||
          info.col < 1 || info.col > fGridY_module) continue;
      const int pad = (fGridY_module - info.col) * fGridX_module + info.row;
      fCanvas->cd(pad);
      // C 분포 위에 S 분포를 겹쳐 그린다.
      fPlotter_Scint.at(i).hist1D->Draw("Hist & sames");
    }
  }

  gSystem->Sleep(1000);
}

void TBplotengine::Update() {

  if (fCalcInfo == TBplotengine::CalcInfo::kAvgTimeStruc)
    for (int i = 0; i < fPlotter_Ceren.size(); i++)
      fPlotter_Ceren.at(i).hist1D->Scale(1./(float)fPlotter_Ceren.at(i).xInit);

  if (fCaseName == "single") {
    if (fCalcInfo == TBplotengine::CalcInfo::kIntADC || fCalcInfo == TBplotengine::CalcInfo::kPeakADC || fCalcInfo == TBplotengine::CalcInfo::kAvgTimeStruc)
      SetMaximum();

    fCanvas->cd();

    if (fCalcInfo == TBplotengine::CalcInfo::kOverlay) {
      fCanvas->cd();
      fPlotter_Ceren.at(0).hist2D->Draw("colz");

    } else {
      fCanvas->cd();
      fMainFrame->Draw();

      double stat_height = (1. - 0.2) / (double)fPlotter_Ceren.size();
      for (int i = 0; i < fPlotter_Ceren.size(); i++) {
        fCanvas->cd();
        fPlotter_Ceren.at(i).hist1D->Draw("Hist & sames");

        if (fIsFirst) {

          if (fCalcInfo == TBplotengine::CalcInfo::kIntADC || fCalcInfo == TBplotengine::CalcInfo::kPeakADC) {
            fCanvas->Update();
            TPaveStats* stat = (TPaveStats*)fPlotter_Ceren.at(i).hist1D->FindObject("stats");
            stat->SetTextColor(fPlotter_Ceren.at(i).hist1D->GetLineColor());
            stat->SetY2NDC(1. - stat_height * i);
            stat->SetY1NDC(1 - stat_height * (i + 1));
            stat->SaveStyle();
          }
        }
      }
      if (fIsFirst) fIsFirst = false;
      if (fCalcInfo == TBplotengine::CalcInfo::kAvgTimeStruc) {
        fCanvas->cd();
        fLeg->Draw("same");
      }
    }
  } else if (fCaseName == "full" || fCaseName == "heatmap") {

    const std::string cerenLabel = (fCaseName == "heatmap") ? " MCPPMT C - "
                                                            : " CERENKOV - ";
    const std::string scintLabel = (fCaseName == "heatmap") ? " MCPPMT S - "
                                                            : " SCINTILLATION - ";

    // 채널이 있으면 첫 분포의 항목 수를 제목에 표시한다.
    const int cerenEntries = fPlotter_Ceren.empty() ? 0 : (int)fPlotter_Ceren.front().hist1D->GetEntries();
    const int scintEntries = fPlotter_Scint.empty() ? 0 : (int)fPlotter_Scint.front().hist1D->GetEntries();

    f2DHistCeren->SetTitle((TString)"Run " + std::to_string(fRunNum) + cerenLabel + std::to_string(cerenEntries));
    for (int i = 0; i < fPlotter_Ceren.size(); i++)
      f2DHistCeren->SetBinContent(fPlotter_Ceren.at(i).info.row, fPlotter_Ceren.at(i).info.col, (int)fPlotter_Ceren.at(i).hist1D->GetMean());

    f2DHistScint->SetTitle((TString)"Run " + std::to_string(fRunNum) + scintLabel + std::to_string(scintEntries));
    for (int i = 0; i < fPlotter_Scint.size(); i++)
      f2DHistScint->SetBinContent(fPlotter_Scint.at(i).info.row, fPlotter_Scint.at(i).info.col, (int)fPlotter_Scint.at(i).hist1D->GetMean());

    fCanvasFull.at(0)->cd(1);
    f2DHistCeren->Draw("colz text");

    fCanvasFull.at(0)->cd(2);
    f2DHistScint->Draw("colz text");

    fCanvasFull.at(0)->Update();

    // full 유형의 타워별 1D 캔버스만 갱신한다.
    if (fCaseName == "full") {
      const size_t nTowerCanvas = fCanvasFull.size() > 1 ? fCanvasFull.size() - 1 : 0;
      const size_t nTowers = std::min({fPlotter_Ceren.size(), fPlotter_Scint.size(), nTowerCanvas});
      for (size_t idx = 0; idx < nTowers; ++idx) {
        const size_t iTower = idx + 1;

        fCanvasFull.at(iTower)->cd(1);
        fPlotter_Ceren.at(idx).hist1D->Draw("Hist");

        fCanvasFull.at(iTower)->cd(2);
        fPlotter_Scint.at(idx).hist1D->Draw("Hist");

        fCanvasFull.at(iTower)->Update();
      }
    }

    if (fIsFirst)fIsFirst = false;
  } else if (fCaseName == "module") {
    // 각 pad의 분포와 캔버스 항목 수를 갱신한다.
    const int cerenEntries = fPlotter_Ceren.empty() ? 0 : (int)fPlotter_Ceren.front().hist1D->GetEntries();
    const std::string moduleLabel = fModule.empty() ? std::string("All") : fModule;
    fCanvas->SetTitle((TString)("Run " + std::to_string(fRunNum) + " " + moduleLabel +
                                " - " + std::to_string(cerenEntries)));

    // 로컬 격자 밖의 좌표는 -1을 반환한다.
    auto padFor = [this](const TButility::mod_info& info) -> int {
      if (info.row < 1 || info.row > fGridX_module ||
          info.col < 1 || info.col > fGridY_module) return -1;
      return (fGridY_module - info.col) * fGridX_module + info.row;
    };

    for (size_t i = 0; i < fPlotter_Ceren.size(); ++i) {
      const int pad = padFor(fPlotter_Ceren.at(i).info);
      if (pad < 0) continue;
      fCanvas->cd(pad);
      fPlotter_Ceren.at(i).hist1D->Draw("Hist");
    }
    for (size_t i = 0; i < fPlotter_Scint.size(); ++i) {
      const int pad = padFor(fPlotter_Scint.at(i).info);
      if (pad < 0) continue;
      fCanvas->cd(pad);
      // C와 S 통계 상자를 함께 유지한다.
      fPlotter_Scint.at(i).hist1D->Draw("Hist & sames");
    }

    // 첫 갱신에서 C와 S 통계 상자를 위아래로 배치한다.
    fCanvas->Update();

    if (fIsFirst) {
      auto place = [](TH1D* h, double y2, double y1, Color_t col) {
        if (!h) return;
        auto* stat = (TPaveStats*)h->FindObject("stats");
        if (!stat) return;
        stat->SetX1NDC(0.62);
        stat->SetX2NDC(0.98);
        stat->SetY1NDC(y1);
        stat->SetY2NDC(y2);
        stat->SetTextColor(col);
        stat->SaveStyle();
      };
      for (size_t i = 0; i < fPlotter_Ceren.size(); ++i) {
        const int pad = padFor(fPlotter_Ceren.at(i).info);
        if (pad < 0) continue;
        fCanvas->cd(pad);
        place(fPlotter_Ceren.at(i).hist1D, 0.99, 0.79, kBlue);
      }
      for (size_t i = 0; i < fPlotter_Scint.size(); ++i) {
        const int pad = padFor(fPlotter_Scint.at(i).info);
        if (pad < 0) continue;
        fCanvas->cd(pad);
        place(fPlotter_Scint.at(i).hist1D, 0.79, 0.59, kRed);
      }
      fCanvas->Update();
      fIsFirst = false;
    }
  }

  // single과 module 유형의 단일 캔버스만 여기서 갱신한다.
  if (fCaseName == "single" || fCaseName == "module") {
    fCanvas->cd();
    fCanvas->Update();
    if (fDraw) fCanvas->Pad()->Draw();
  }

  // 임시 ROOT 파일을 완성한 뒤 최종 이름으로 바꾼다.
  std::string basePrefix;
  if (fCaseName == "full") {
    basePrefix = "Run" + std::to_string(fRunNum) + "_" + fCaseName + "_" + fMethod;
    if (fAuxCut) basePrefix += "_AuxCut";
    TString output    = (TString)("./output/" + basePrefix + ".root");
    TString tmpOutput = (TString)("./output/" + basePrefix + ".tmp.root");
    {
      TFile outoutFile(tmpOutput, "RECREATE");
      outoutFile.cd();
      for (int i = 0; i < fCanvasFull.size(); i++)
        fCanvasFull.at(i)->Write();
      outoutFile.Close();
    }
    std::rename(tmpOutput.Data(), output.Data());
  } else if (fCaseName == "heatmap") {
    basePrefix = "Run" + std::to_string(fRunNum) + "_" + fCaseName + "_" + fMethod + "_" + fModule;
    if (fAuxCut) basePrefix += "_AuxCut";
    TString output    = (TString)("./output/" + basePrefix + ".root");
    TString tmpOutput = (TString)("./output/" + basePrefix + ".tmp.root");
    {
      TFile outoutFile(tmpOutput, "RECREATE");
      outoutFile.cd();
      for (int i = 0; i < fCanvasFull.size(); i++)
        fCanvasFull.at(i)->Write();
      outoutFile.Close();
    }
    std::rename(tmpOutput.Data(), output.Data());
  } else if (fCaseName == "module") {
    // 모듈을 지정하지 않으면 출력 이름에 All을 사용한다.
    const std::string moduleTag = fModule.empty() ? std::string("All") : fModule;
    basePrefix = "Run" + std::to_string(fRunNum) + "_" + fCaseName + "_" + fMethod + "_" + moduleTag;
    if (fAuxCut) basePrefix += "_AuxCut";
    TString output    = (TString)("./output/" + basePrefix + ".root");
    TString tmpOutput = (TString)("./output/" + basePrefix + ".tmp.root");
    {
      TFile outoutFile(tmpOutput, "RECREATE");
      outoutFile.cd();
      fCanvas->Write();
      outoutFile.Close();
    }
    std::rename(tmpOutput.Data(), output.Data());
  } else {
    basePrefix = "Run" + std::to_string(fRunNum) + "_" + fCaseName + "_" + fMethod + "_" + fModule;
    if (fAuxCut) basePrefix += "_AuxCut";
    TString output    = (TString)("./output/" + basePrefix + ".root");
    TString tmpOutput = (TString)("./output/" + basePrefix + ".tmp.root");
    {
      TFile outoutFile(tmpOutput, "RECREATE");
      outoutFile.cd();
      fCanvas->Write();
      outoutFile.Close();
    }
    std::rename(tmpOutput.Data(), output.Data());
  }


  if (fDraw) {
    if (fLive && fUsingAUX) gSystem->ProcessEvents();
    if (fLive && !fUsingAUX) gSystem->ProcessEvents();
    if (!fLive && fUsingAUX) gSystem->ProcessEvents();
    if (!fLive && !fUsingAUX) fApp->Run(false);
  }



  gSystem->Sleep(1000);

  if (fLive)
    if (fCalcInfo == TBplotengine::CalcInfo::kAvgTimeStruc)
      for (int i = 0; i < fPlotter_Ceren.size(); i++)
        fPlotter_Ceren.at(i).hist1D->Scale((float)fPlotter_Ceren.at(i).xInit);


}

void TBplotengine::SetMaximum() {

  float max = -999;
  for (int i = 0; i < fPlotter_Ceren.size(); i++) {
    if (max < fPlotter_Ceren.at(i).hist1D->GetMaximum()) {
      max = fPlotter_Ceren.at(i).hist1D->GetMaximum();
    }
  }

  fMainFrame->GetYaxis()->SetRangeUser(0., max * 1.2);
}

void TBplotengine::SaveAs(TString output = "")
{
  if (output == "")
    output = "./output/Run" + std::to_string(fRunNum) + "_" + fCaseName + "_" + fMethod + "_" + fModule + ".root";

  TFile* outoutFile = new TFile(output, "RECREATE");

  outoutFile->cd();
  if (fCaseName == "single") {
    if (fMethod == "Overlay") {
      for (int i = 0; i < fPlotter_Ceren.size(); i++)
        fPlotter_Ceren.at(i).hist2D->Write();
    } else {
      for (int i = 0; i < fPlotter_Ceren.size(); i++)
        fPlotter_Ceren.at(i).hist1D->Write();
    }
  }

  outoutFile->Close();
}

std::vector<int> TBplotengine::GetUniqueMID() {
  if (fCaseName == "single") {
    return fUtility.GetUniqueMID(fCIDtoPlot_Ceren);
  } else if (fCaseName == "full" || fCaseName == "heatmap" || fCaseName == "module") {
    return fUtility.GetUniqueMID(fCIDtoPlot_Ceren, fCIDtoPlot_Scint);
  }

  return std::vector<int>{};
}
