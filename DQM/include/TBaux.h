#ifndef TBaux_h
#define TBaux_h 1

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
#include "TBplotengine.h"
#include "TBmid.h"
#include "TBevt.h"

#include "TH1.h"
#include "TH2.h"
#include "TFile.h"
#include "TCanvas.h"
#include "TApplication.h"
#include "TLegend.h"

class TBaux
{
public:
  TBaux() = default;
  TBaux(const YAML::Node fNodePlot_, int fRunNum_, bool fPlotting_, bool fLive_, bool fDraw_, TButility fUtility_);
  ~TBaux() {}

  void init();

  void Fill(TBevt<TBwaveform> anEvent);
  void Fill(TBevt<TBfastmode> anEvent) {}

  float LinearInterp(float x1, float y1, float x2, float y2, float threshold) const;
  float GetLeadingEdgeBin(const std::vector<float>& waveform, float percent) const;
  std::vector<float> GetPosition(const std::vector<std::vector<float>>& wave); // WCX, WCY, NIM



  void Draw();
  void Update();

  void SaveAs(TString output = "");

  // 이벤트별 최댓값으로 16×16 호도스코프 맵을 채운다.
  void FillHodoscope(TBevt<TBwaveform> anEvent);

  // 가장 밝은 섬유의 IntADC·PeakADC X/Y 위치를 반환한다.
  std::vector<float> GetHodoscopeRawPosition(TBevt<TBwaveform> anEvent);

  // 채널별 pedestal 구간을 반환하며 기본값은 100 bin이다.
  double GetPeakADC(std::vector<short> waveform, int xInit, int xFin, int pedBins = 100);
  double GetIntADC(std::vector<short> waveform, int xInit, int xFin, int pedBins = 100);

  int PedBinsForChannel(const std::string& name) const { return fPedConfig.BinsFor(name); }

  double GetValue(std::vector<short> waveform, int xInit, int xFin, const std::string& name = "") {

    const int pedBins = PedBinsForChannel(name);

    if(fMethod == "PeakADC")
      return GetPeakADC(waveform, xInit, xFin, pedBins);

    if(fMethod == "IntADC")
      return GetIntADC(waveform, xInit, xFin, pedBins);

    return -999;
  }

  // See TBplotengine::SetPedestalBins for semantics.
  void SetPedestalBins(const YAML::Node& node) { fPedConfig.Load(node); }

  std::vector<int> GetUniqueMID() {

    return fUtility.GetUniqueMID(fCIDtoPlot);
  }

  void SetRange(const YAML::Node tConfigNode);
  void SetMethod(std::string fMethod_) { 
    fMethod = fMethod_; 
    if (fMethod == "Overlay" || fMethod == "Avg") fMethod = "IntADC";
  }
  void SetApp(TApplication* fApp_) { fApp = fApp_; }
  void SetAUXCut(bool fAuxCut_) { fAuxCut = fAuxCut_; }
  // AUX 컷 범위는 WC 또는 WCHodo이다.
  void SetAUXCutMode(const std::string& fAuxCutMode_) { fAuxCutMode = fAuxCutMode_; }
  // 초기화 전에 플롯에 사용할 AUX 장비 범위를 지정한다.
  void SetAUXMode(const std::string& fAuxMode_) { fAuxMode = fAuxMode_; }
  void SetParticle(std::string fParticle_);

  bool IsPassing(TBevt<TBwaveform> anEvent);

  void SetMaximum();

private:
  const YAML::Node fNodeAux;
  int fRunNum;
  bool fPlotting;
  bool fLive;
  bool fDraw;
  bool fAuxCut;
  // AUXcut mode: "WC" (default) or "WCHodo". See SetAUXCutMode().
  std::string fAuxCutMode;
  // AUX scope mode: "WC" | "Hodo" | "WCHodo". See SetAUXMode().
  // AUX 장비 범위의 기본값은 WCHodo이다.
  std::string fAuxMode;
  // WCHodo 기울기 컷 [X, Y]이며 기본값은 [4, 4] mm이다.
  std::vector<double> fInclinationCut;
  std::string fParticle;

  TButility fUtility;

  TApplication* fApp;
  TCanvas* fCanvas;

  bool fIsFirst;

  std::string fMethod;

  TH2D* fWCPosition;

  double fWCThreshold;
  double fWCCalibration;
  std::vector<double> fWCReference; // timing reference per axis
  double fWCPosCut;

  std::vector<TBcid> fCIDtoPlot;
  std::map<std::string, std::vector<int>> fRangeMap;

  // WCX, WCY, NIM 채널이 모두 매핑됐는지 나타낸다.
  bool fWCEnabled;
  TBcid fCID_WCX;
  TBcid fCID_WCY;
  TBcid fCID_NIM;

  // 16×16 호도스코프 채널과 출력 객체.
  bool fHodoEnabled;
  std::vector<TBcid> fCID_HodoX;   // 16 entries
  std::vector<TBcid> fCID_HodoY;   // 16 entries
  // 섬유별 IntADC·PeakADC 검색 구간이며 기본값은 [150, 350]이다.
  std::vector<int> fHodoFirstX;    // 16 entries
  std::vector<int> fHodoLastX;     // 16 entries
  std::vector<int> fHodoFirstY;    // 16 entries
  std::vector<int> fHodoLastY;     // 16 entries
  // 보정 전 빔 중심 섬유 위치이며 기본값은 (8, 8)이다.
  std::vector<float> fHodoCenter;
  // 기울기 컷에 사용할 IntADC 또는 PeakADC 위치 방식.
  std::string fHodoCutMethod;
  // 호도스코프 채널별 IntADC·PeakADC 정규화 상수.
  std::vector<double> fHodoNormIntADC_X;   // 16 entries (HX1..HX16)
  std::vector<double> fHodoNormIntADC_Y;   // 16 entries (HY1..HY16)
  std::vector<double> fHodoNormPeakADC_X;  // 16 entries (HX1..HX16)
  std::vector<double> fHodoNormPeakADC_Y;  // 16 entries (HY1..HY16)
  // 이벤트별 최댓값 섬유의 원시 hit map.
  TH2F* fHodoIntADC;
  TH2F* fHodoPeakADC;
  TCanvas* fCanvasHodoIntADC;
  TCanvas* fCanvasHodoPeakADC;
  // 빔 중심을 (8, 8)에 맞춘 보정 hit map.
  TH2F* fHodoIntADC_corr;
  TH2F* fHodoPeakADC_corr;
  TCanvas* fCanvasHodoIntADC_corr;
  TCanvas* fCanvasHodoPeakADC_corr;

  // Per-channel pedestal bin window; see TBplotengine::fPedConfig.
  TBpedConfig fPedConfig;
};








#endif
