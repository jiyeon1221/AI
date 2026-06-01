#ifndef TBsingleWaveform_h
#define TBsingleWaveform_h 1

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
#include "TButility.h"
#include "TBdetector.h"
#include "TBmid.h"
#include "TBevt.h"
#include "TBread.h"
#include "TBobject.h"

#include "TH1.h"
#include "TH2.h"
#include "TFile.h"
#include "TCanvas.h"
#include "TApplication.h"
#include "TLegend.h"

class TBsingleWaveform
{
public:
  TBsingleWaveform(ObjectCollection* fObj);
  ~TBsingleWaveform() {}

  void init();
  void Loop();

  std::vector<int> GetUniqueMID();

  void GetFormattedRamInfo();
  void SetMaximum();

private:
  int fRunNum;
  int fMaxEvent;
  int fSkipEvent;
  TString fOutputName;

  TBconfig fConfig;
  TButility fUtility;

  std::string fBaseDir;

  std::vector<TH1D*> fHistWaveform;
  TCanvas* fCanvas;
  TLegend* fLeg;

  TH1D* fMainFrame;

  std::vector<std::string> fNametoPlot;
  std::vector<TBcid> fCIDtoPlot;
};

#endif
