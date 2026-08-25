#ifndef TBmonit_h
#define TBmonit_h 1

#include <string>
#include <iostream>

#include "TFile.h"
#include "TBconfig.h"
#include "TBread.h"
#include "TBobject.h"

template <class T>
class TBmonit
{
public:
  TBmonit(const std::string &fConfig_, int fRunNum_);
  TBmonit(ObjectCollection* obj);

  ~TBmonit() {}

  void Loop();
  void LoopLive();
  void LoopAfterRun();


  void SetMaxEvent(int fMaxEvent_) { fMaxEvent = fMaxEvent_; }
  void SetMaxFile(int fMaxFile_) { fMaxFile = fMaxFile_; }
  void SetLive() { fIsLive = true; }
  void GetFormattedRamInfo();

private:
  TBconfig fConfig;

  ObjectCollection* fObj;
  TButility fUtility;

  TApplication* fApp;

  std::string fBaseDir;
  std::string fMapping;
  std::string fParticle;

  int fRunNum;
  int fMaxEvent;
  int fMaxFile;

  bool fIsLive;
  bool fDraw;
  bool fAuxPlotting;
  bool fAuxCut;
  // AUX cut 범위: WC 또는 WCHodo.
  std::string fAuxCutMode;
  // AUX 플롯 대상: WC, Hodo 또는 WCHodo.
  std::string fAuxMode;
};

#endif
