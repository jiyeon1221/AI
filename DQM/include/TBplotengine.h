#ifndef TBplotengine_h
#define TBplotengine_h 1

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

#include "TBconfig.h"
#include "TBpedConfig.h"
#include "TButility.h"
#include "TBdetector.h"
#include "TBmid.h"
#include "TBevt.h"

#include "TH1.h"
#include "TH2.h"
#include "TFile.h"
#include "TCanvas.h"
#include "TApplication.h"
#include "TLegend.h"

class TBplotengine
{
public:
  TBplotengine() = default;
  TBplotengine(const YAML::Node fNodePlot_, int fRunNum_, bool fLive_, bool fDraw_, TButility fUtility_);
  ~TBplotengine() {}

  enum CalcInfo
  {
    kIntADC = 0,
    kPeakADC,
    kAvgTimeStruc,
    kOverlay,
    kAux
  };

  struct PlotInfo {
    TBcid cid;
    std::string name;
    TButility::mod_info info;

    TH2D* hist2D;
    TH1D* hist1D;

    int xInit;
    int xFin;

    PlotInfo(TBcid cid_, std::string name_, TButility::mod_info info_)
    : cid(cid_), name(name_), info(info_), xInit(0), xFin(0)
    {}

    PlotInfo(TBcid cid_, std::string name_, TButility::mod_info info_, int xInit_, int xFin_)
    : cid(cid_), name(name_), info(info_), xInit(xInit_), xFin(xFin_)
    {}

    void SetPlot(TH1D* aHist) { hist1D = aHist; }
    void SetPlot(TH2D* aHist) { hist2D = aHist; }
  };

  void init();
  void init_full();
  void init_Generic();
  // MCPPMT C/S 64채널의 8×8 heatmap을 초기화한다.
  void init_MCPPMT();
  // 매핑과 모듈 접두사로 타워별 분포 격자를 초기화한다.
  void init_module();
  void PrintInfo();

  void Fill(TBevt<TBwaveform> anEvent);
  void Fill(TBevt<TBfastmode> anEvent) {}

  void Draw();
  void Update();
  void SetMaximum();

  void SaveAs(TString output);

  // 채널별 pedestal 구간을 반환하며 기본값은 100 bin이다.
  double GetPeakADC(std::vector<short> waveform, int xInit, int xFin, int pedBins = 100);
  double GetIntADC(std::vector<short> waveform, int xInit, int xFin, int pedBins = 100);

  int PedBinsForChannel(const std::string& name) const { return fPedConfig.BinsFor(name); }

  double GetValue(std::vector<short> waveform, int xInit, int xFin, const std::string& name = "") {

    const int pedBins = PedBinsForChannel(name);

    if(fCalcInfo == CalcInfo::kPeakADC)
      return GetPeakADC(waveform, xInit, xFin, pedBins);

    if(fCalcInfo == CalcInfo::kIntADC)
      return GetIntADC(waveform, xInit, xFin, pedBins);

    return -999;
  }

  // PedestalBins 설정을 적용한다.
  void SetPedestalBins(const YAML::Node& node) { fPedConfig.Load(node); }

  std::vector<int> GetUniqueMID();

  void SetCID(std::vector<TBcid> cids) { fCIDtoPlot_Ceren = cids; }
  void SetCID(std::vector<std::string> names) { fNametoPlot = names; }

  void SetCase(std::string cases) { fCaseName = cases; }
  void SetModule(std::string module) { fModule = module; }

  void SetMethod(std::string fMethod_) {
    fMethod = fMethod_;

    if (fMethod == "IntADC")
      fCalcInfo = kIntADC;

    if (fMethod == "PeakADC")
      fCalcInfo = kPeakADC;

    if (fMethod == "Avg")
      fCalcInfo = kAvgTimeStruc;

    if (fMethod == "Overlay")
      fCalcInfo = kOverlay;

    if (fMethod == "AUX")
      fCalcInfo = kAux;
  }

  void SetApp(TApplication* fApp_) { fApp = fApp_; }
  void SetAUX() { fUsingAUX = true; }
  void SetAUXCut(bool fAuxCut_) { fAuxCut = fAuxCut_; }

private:
  const YAML::Node fConfig;
  int fRunNum;
  TButility fUtility;

  bool fDraw;
  bool fIsFirst;
  bool fLive;
  bool fUsingAUX;
  bool fAuxCut;

  TApplication* fApp;
  TCanvas* fCanvas;
  std::vector<TCanvas*> fCanvasFull;

  TLegend* fLeg;

  CalcInfo fCalcInfo;

  std::string fCaseName;
  std::string fModule;
  std::string fMethod;

  TH2D* f2DHistCeren;
  TH2D* f2DHistScint;

  TH1D* fMainFrame;

  std::vector<std::string> fNametoPlot;

  std::vector<TBcid> fCIDtoPlot_Ceren;
  std::vector<TBcid> fCIDtoPlot_Scint;

  std::vector<PlotInfo> fPlotter_Ceren;
  std::vector<PlotInfo> fPlotter_Scint;

  // module 유형의 로컬 격자 크기.
  int fGridX_module = 0;
  int fGridY_module = 0;

  // 설정에서 읽은 채널별 pedestal 구간.
  TBpedConfig fPedConfig;
};

#endif
