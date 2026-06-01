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

  // Hodoscope filling (16x16 fiber map of the highest-amplitude X/Y bin per
  // event). Called from Fill() when --AUX is set.
  void FillHodoscope(TBevt<TBwaveform> anEvent);

  // Brightest-fiber positions in fiber coordinates (= mm; 1 fiber = 1 mm).
  // Returns { x_intADC, y_intADC, x_peakADC, y_peakADC } as raw bin
  // centers (range 0..16). Empty vector if the hodoscope is disabled or
  // channel data is missing. Used both by FillHodoscope() and by
  // IsPassing() (for the WC+Hodo inclination cut).
  std::vector<float> GetHodoscopeRawPosition(TBevt<TBwaveform> anEvent);

  // Pedestal window length used by Get{Int,Peak}ADC. Configurable per
  // channel name through config_general.yml::PedestalBins (see TBpedConfig).
  // Default 100 bins if no rule matches.
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
  // AUXcut mode: "WC" applies only the WC POSCUT (legacy behavior),
  // "WCHodo" additionally requires |WC_corr − Hodo_corr| < INCLINATION_CUT
  // on both axes. Any unrecognised value falls back to "WC".
  void SetAUXCutMode(const std::string& fAuxCutMode_) { fAuxCutMode = fAuxCutMode_; }
  // AUX scope mode: "WC" | "Hodo" | "WCHodo". Selects which AUX
  // subsystems to plot. Must be called BEFORE init() so the CID
  // resolution can skip subsystems the operator didn't ask for —
  // critical when one of the subsystems (e.g. hodoscope MID 17) is
  // physically absent from the setup. Unrecognised values are normalised
  // to "WCHodo" inside init().
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
  // Default "WCHodo" preserves legacy behaviour: --AUX without an
  // explicit --AUXMode still plots both subsystems.
  std::string fAuxMode;
  // Beam-inclination cut (mm) for the WCHodo mode. Read from
  // AUX.INCLINATION_CUT; defaults to [4, 4]. Stored as 2 entries
  // [X_cut, Y_cut]; if the YAML provides fewer entries the default
  // is kept.
  std::vector<double> fInclinationCut;
  std::string fParticle;

  TButility fUtility;

  TApplication* fApp;
  TCanvas* fCanvas;

  bool fIsFirst;

  std::string fMethod;

  TH2D* fWCPosition;

  // TH1D* fPS;
  // TH1D* fMC;
  // TH1D* fTC;
  // TH1D* fCC1;
  // TH1D* fCC2;

  // TH1D* fFrameTop;
  // TH1D* fFrameBot;

  // double fPScut;
  // double fPSInitCut;
  // double fPSFinCut;
  // double fMCcut;
  // double fCC1cut;
  // double fCC2cut;
  double fWCThreshold;
  double fWCCalibration;
  std::vector<double> fWCReference; // timing reference per axis
  double fWCPosCut;

  std::vector<TBcid> fCIDtoPlot;
  std::map<std::string, std::vector<int>> fRangeMap;

  // True only when all three WC channels (WCX/WCY/NIM) resolved to valid
  // CIDs in the loaded mapping. Used to gate Fill()/IsPassing() so a mapping
  // without WC (e.g. mapping_TB2025_v1.root for MCPPMT runs) doesn't crash
  // when --AUX or --AUXcut is requested.
  bool fWCEnabled;
  TBcid fCID_WCX;
  TBcid fCID_WCY;
  TBcid fCID_NIM;

  // ── Hodoscope (16 X-fibers × 16 Y-fibers) ───────────────────────────────
  // Channel-name lists currently use the dummy tower-channel names from
  // draw_hodoscope.cc; once the proper hodoscope mapping is delivered they
  // can be swapped for X1..X16 / Y1..Y16 without touching the logic.
  bool fHodoEnabled;
  std::vector<TBcid> fCID_HodoX;   // 16 entries
  std::vector<TBcid> fCID_HodoY;   // 16 entries
  // Per-fiber search-window [first, last] for the brightest-fiber scan.
  // The same window feeds both GetIntADC and GetPeakADC for that fiber.
  // Read from ModuleConfig.HX1..HX16 / HY1..HY16 in SetRange(); falls back
  // to (150, 350) per fiber when an entry is missing.
  std::vector<int> fHodoFirstX;    // 16 entries
  std::vector<int> fHodoLastX;     // 16 entries
  std::vector<int> fHodoFirstY;    // 16 entries
  std::vector<int> fHodoLastY;     // 16 entries
  // Reference fiber position (X_ref, Y_ref) where the beam-center sits
  // before any correction. Read from AUX.Hodoscope.CENTER; defaults to
  // the nominal center (8, 8) which means "no correction".
  std::vector<float> fHodoCenter;
  // Which brightest-fiber metric feeds the WC↔Hodo inclination cut.
  // Read from AUX.Hodoscope.CUT_METHOD; "IntADC" (default) or "PeakADC".
  // Unrelated to fMethod (which controls the *main* DQM plots).
  std::string fHodoCutMethod;
  // Per-channel normalization constants read from config_general.yml
  // (AUX.Hodoscope.NORM_CONST_INTADC / NORM_CONST_PEAKADC).
  // calibrated = raw / norm_const; all 1.0 means no normalization.
  std::vector<double> fHodoNormIntADC_X;   // 16 entries (HX1..HX16)
  std::vector<double> fHodoNormIntADC_Y;   // 16 entries (HY1..HY16)
  std::vector<double> fHodoNormPeakADC_X;  // 16 entries (HX1..HX16)
  std::vector<double> fHodoNormPeakADC_Y;  // 16 entries (HY1..HY16)
  // Raw hit-map of the brightest X/Y fiber per event.
  TH2F* fHodoIntADC;
  TH2F* fHodoPeakADC;
  TCanvas* fCanvasHodoIntADC;
  TCanvas* fCanvasHodoPeakADC;
  // Same maps, shifted by -fHodoCenter + (8, 8) so the beam appears at
  // the nominal hodoscope center.
  TH2F* fHodoIntADC_corr;
  TH2F* fHodoPeakADC_corr;
  TCanvas* fCanvasHodoIntADC_corr;
  TCanvas* fCanvasHodoPeakADC_corr;

  // Per-channel pedestal bin window; see TBplotengine::fPedConfig.
  TBpedConfig fPedConfig;
};








#endif
