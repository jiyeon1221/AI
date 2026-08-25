#include "TBaux.h"
#include "GuiTypes.h"
#include "TSystem.h"
#include "TStyle.h"
#include <sys/types.h>


TBaux::TBaux(const YAML::Node fNodePlot_, int fRunNum_, bool fPlotting_, bool fLive_, bool fDraw_, TButility fUtility_)
: fNodeAux(fNodePlot_),
  fRunNum(fRunNum_),
  fPlotting(fPlotting_),
  fLive(fLive_),
  fDraw(fDraw_),
  fAuxCut(false),
  fAuxCutMode("WC"),
  fAuxMode("WCHodo"),
  fInclinationCut({4.0, 4.0}),
  fUtility(fUtility_),
  fApp(nullptr),
  fCanvas(nullptr),
  fIsFirst(true),
  fMethod(""),
  fWCPosition(nullptr),
  fWCThreshold(0.3),
  fWCCalibration(0.05),
  fWCReference(2, 0.),
  fWCPosCut(-1.),
  fWCEnabled(false),
  fCID_WCX(),
  fCID_WCY(),
  fCID_NIM(),
  fHodoEnabled(false),
  fCID_HodoX(),
  fCID_HodoY(),
  fHodoFirstX(16, 150),
  fHodoLastX(16, 350),
  fHodoFirstY(16, 150),
  fHodoLastY(16, 350),
  fHodoCenter(2, 8.0f),
  fHodoCutMethod("IntADC"),
  fHodoNormIntADC_X(16, 1.0),
  fHodoNormIntADC_Y(16, 1.0),
  fHodoNormPeakADC_X(16, 1.0),
  fHodoNormPeakADC_Y(16, 1.0),
  fHodoIntADC(nullptr),
  fHodoPeakADC(nullptr),
  fCanvasHodoIntADC(nullptr),
  fCanvasHodoPeakADC(nullptr),
  fHodoIntADC_corr(nullptr),
  fHodoPeakADC_corr(nullptr),
  fCanvasHodoIntADC_corr(nullptr),
  fCanvasHodoPeakADC_corr(nullptr)
{}

void TBaux::init() {

  const auto nodeWC = fNodeAux["WC"];
  if (!nodeWC) {
    throw std::runtime_error("AUX.WC is not configured in YAML.");
  }

  if (nodeWC["CALIB"]) {
    fWCCalibration = nodeWC["CALIB"].as<double>();
  } else {
    throw std::runtime_error("AUX.WC.CALIB is missing in YAML.");
  }

  if (nodeWC["CENTER"]) {
    fWCReference = nodeWC["CENTER"].as<std::vector<double>>();
    if (fWCReference.size() != 2) {
      throw std::runtime_error("AUX.WC.CENTER must contain exactly two values (X_ref, Y_ref).");
    }
  } else {
    throw std::runtime_error("AUX.WC.CENTER is missing in YAML.");
  }

  if (nodeWC["THRESHOLD"])
    fWCThreshold = nodeWC["THRESHOLD"].as<double>();

  if (nodeWC["POSCUT"])
    fWCPosCut = nodeWC["POSCUT"].as<double>();

  // 플롯과 컷 설정에서 필요한 AUX 장비만 선택한다.
  if (fAuxMode != "WC" && fAuxMode != "Hodo" && fAuxMode != "WCHodo") {
    std::cout << "[TBaux] Unrecognised --AUXMode '" << fAuxMode
              << "', falling back to 'WCHodo'." << std::endl;
    fAuxMode = "WCHodo";
  }
  const bool modeWantsWC   = (fAuxMode != "Hodo");
  const bool modeWantsHodo = (fAuxMode != "WC");
  const bool needWC   = (fPlotting && modeWantsWC)   || fAuxCut;
  const bool needHodo = (fPlotting && modeWantsHodo) || (fAuxCut && fAuxCutMode == "WCHodo");

  std::cout << "[TBaux] AUXMode='" << fAuxMode
            << "' AUXcut=" << (fAuxCut ? "on" : "off")
            << " AUXCutMode='" << fAuxCutMode << "'"
            << " → load WC=" << (needWC ? "yes" : "no")
            << ", load Hodo=" << (needHodo ? "yes" : "no")
            << std::endl;

  // 필요한 경우에만 WC 채널을 매핑한다.
  auto cidValid = [](const TBcid& c) { return c.mid() >= 0 && c.channel() >= 0; };

  fCIDtoPlot.clear();
  if (needWC) {
    fCID_WCX = fUtility.GetCID("WCX");
    fCID_WCY = fUtility.GetCID("WCY");
    fCID_NIM = fUtility.GetCID("NIM");
    fWCEnabled = cidValid(fCID_WCX) && cidValid(fCID_WCY) && cidValid(fCID_NIM);
    if (!fWCEnabled) {
      std::cout << "[TBaux] WC channels missing from the loaded mapping "
                << "(WCX/WCY/NIM); --AUX plots and --AUXcut will be skipped."
                << std::endl;
    } else {
      // 유효한 CID만 읽기 목록에 추가한다.
      fCIDtoPlot.push_back(fCID_WCX);
      fCIDtoPlot.push_back(fCID_WCY);
      fCIDtoPlot.push_back(fCID_NIM);
    }
  } else {
    // WC가 필요하지 않으면 관련 처리를 비활성화한다.
    fWCEnabled = false;
    std::cout << "[TBaux] WC plots/cut not requested (AUXMode='" << fAuxMode
              << "', AUXcut=" << (fAuxCut ? "on" : "off") << ")"
              << " — skipping WC channel load." << std::endl;
  }

  // WC 사용 시에만 히스토그램과 캔버스를 만든다.
  if (needWC) {
    fWCPosition = new TH2D(
      "WC_Position",
      (TString)"Run " + std::to_string(fRunNum) + " Wire Chamber position;X [mm];Y [mm]",
      120, -30., 30., 120, -30., 30.);
    fWCPosition->SetStats(0);

    fCanvas = new TCanvas("fCanvas_WC", "fCanvas_WC", 1200, 800);
    fCanvas->Divide(1, 1);
    fCanvas->cd(1)->SetRightMargin(0.13);
  }

  // 호도스코프 중심, 컷 방식, 정규화 설정을 읽는다.
  const auto nodeHodo = fNodeAux["Hodoscope"];
  if (nodeHodo && nodeHodo["CENTER"]) {
    const auto c = nodeHodo["CENTER"].as<std::vector<float>>();
    if (c.size() == 2) fHodoCenter = c;
  }
  if (nodeHodo && nodeHodo["CUT_METHOD"]) {
    const auto m = nodeHodo["CUT_METHOD"].as<std::string>();
    if (m == "IntADC" || m == "PeakADC") {
      fHodoCutMethod = m;
    } else {
      std::cout << "[TBaux] Unrecognised AUX.Hodoscope.CUT_METHOD '" << m
                << "'. Falling back to '" << fHodoCutMethod << "'." << std::endl;
    }
  }

  // HX/HY 16개 채널의 정규화 상수를 읽는다.
  auto loadNormConst = [](const YAML::Node& node, std::vector<double>& dst) {
    if (!node) return;
    const auto v = node.as<std::vector<double>>();
    if (v.size() != 16) return;
    for (int i = 0; i < 16; ++i)
      dst[i] = (v[i] > 1e-9) ? v[i] : 1.0;
  };

  if (nodeHodo && nodeHodo["NORM_CONST_INTADC"]) {
    loadNormConst(nodeHodo["NORM_CONST_INTADC"]["HX"], fHodoNormIntADC_X);
    loadNormConst(nodeHodo["NORM_CONST_INTADC"]["HY"], fHodoNormIntADC_Y);
  }
  if (nodeHodo && nodeHodo["NORM_CONST_PEAKADC"]) {
    loadNormConst(nodeHodo["NORM_CONST_PEAKADC"]["HX"], fHodoNormPeakADC_X);
    loadNormConst(nodeHodo["NORM_CONST_PEAKADC"]["HY"], fHodoNormPeakADC_Y);
  }

  // WCHodo 모드의 X/Y 기울기 컷을 읽는다.
  if (fNodeAux["INCLINATION_CUT"]) {
    const auto v = fNodeAux["INCLINATION_CUT"].as<std::vector<double>>();
    if (v.size() == 2) fInclinationCut = v;
  }

  // 필요한 경우 HX/HY 16개 채널과 히스토그램을 순서대로 만든다.
  if (needHodo) {
    const std::vector<std::string> hodoX_names = {
      "HX1","HX2","HX3","HX4","HX5","HX6","HX7","HX8",
      "HX9","HX10","HX11","HX12","HX13","HX14","HX15","HX16"
    };
    const std::vector<std::string> hodoY_names = {
      "HY1","HY2","HY3","HY4","HY5","HY6","HY7","HY8",
      "HY9","HY10","HY11","HY12","HY13","HY14","HY15","HY16"
    };

    fCID_HodoX.clear();
    fCID_HodoY.clear();
    fCID_HodoX.reserve(hodoX_names.size());
    fCID_HodoY.reserve(hodoY_names.size());
    for (const auto& n : hodoX_names) fCID_HodoX.push_back(fUtility.GetCID(n));
    for (const auto& n : hodoY_names) fCID_HodoY.push_back(fUtility.GetCID(n));

    // 모든 HX/HY 채널이 매핑된 경우에만 활성화한다.
    bool hodoAllValid = true;
    for (const auto& cid : fCID_HodoX) hodoAllValid &= cidValid(cid);
    for (const auto& cid : fCID_HodoY) hodoAllValid &= cidValid(cid);
    if (!hodoAllValid) {
      std::cout << "[TBaux] Hodoscope channels missing from the loaded mapping "
                << "(HX1..HX16 / HY1..HY16); hodoscope AUX plots will be skipped."
                << std::endl;
    } else {
      // 완전한 채널 매핑만 읽기 목록에 추가한다.
      for (const auto& cid : fCID_HodoX) fCIDtoPlot.push_back(cid);
      for (const auto& cid : fCID_HodoY) fCIDtoPlot.push_back(cid);
    }

    fHodoIntADC = new TH2F(
      "hodoscope_intADC",
      (TString)"Run " + std::to_string(fRunNum) + " Hodoscope IntADC;X [fiber];Y [fiber];events",
      16, 0., 16., 16, 0., 16.);
    fHodoIntADC->SetStats(0);

    fHodoPeakADC = new TH2F(
      "hodoscope_peakADC",
      (TString)"Run " + std::to_string(fRunNum) + " Hodoscope PeakADC;X [fiber];Y [fiber];events",
      16, 0., 16., 16, 0., 16.);
    fHodoPeakADC->SetStats(0);

    fCanvasHodoIntADC = new TCanvas("fCanvas_HodoIntADC", "fCanvas_HodoIntADC", 800, 800);
    fCanvasHodoIntADC->cd()->SetRightMargin(0.13);

    fCanvasHodoPeakADC = new TCanvas("fCanvas_HodoPeakADC", "fCanvas_HodoPeakADC", 800, 800);
    fCanvasHodoPeakADC->cd()->SetRightMargin(0.13);

    fHodoIntADC_corr = new TH2F(
      "hodoscope_intADC_corr",
      (TString)"Run " + std::to_string(fRunNum) + " Hodoscope IntADC (center-corrected);X [fiber];Y [fiber];events",
      16, 0., 16., 16, 0., 16.);
    fHodoIntADC_corr->SetStats(0);

    fHodoPeakADC_corr = new TH2F(
      "hodoscope_peakADC_corr",
      (TString)"Run " + std::to_string(fRunNum) + " Hodoscope PeakADC (center-corrected);X [fiber];Y [fiber];events",
      16, 0., 16., 16, 0., 16.);
    fHodoPeakADC_corr->SetStats(0);

    fCanvasHodoIntADC_corr = new TCanvas("fCanvas_HodoIntADC_corr", "fCanvas_HodoIntADC_corr", 800, 800);
    fCanvasHodoIntADC_corr->cd()->SetRightMargin(0.13);

    fCanvasHodoPeakADC_corr = new TCanvas("fCanvas_HodoPeakADC_corr", "fCanvas_HodoPeakADC_corr", 800, 800);
    fCanvasHodoPeakADC_corr->cd()->SetRightMargin(0.13);

    fHodoEnabled = hodoAllValid;
  } else {
    std::cout << "[TBaux] Hodo plots/cut not requested (AUXMode='" << fAuxMode
              << "', AUXCutMode='" << fAuxCutMode << "')"
              << " — skipping hodoscope channel load (no MID 17 read)."
              << std::endl;
    fHodoEnabled = false;
  }
}

void TBaux::SetParticle(std::string fParticle_) {

  fParticle = fParticle_;

}

void TBaux::SetRange(const YAML::Node tConfigNode) {

  // 각 섬유의 IntADC·PeakADC 검색 구간을 설정에서 읽는다.
  for (int i = 0; i < 16; ++i) {
    const std::string nameX = "HX" + std::to_string(i + 1);
    const std::string nameY = "HY" + std::to_string(i + 1);
    if (tConfigNode[nameX]) {
      const auto r = tConfigNode[nameX].as<std::vector<int>>();
      if (r.size() == 2) { fHodoFirstX[i] = r[0]; fHodoLastX[i] = r[1]; }
    }
    if (tConfigNode[nameY]) {
      const auto r = tConfigNode[nameY].as<std::vector<int>>();
      if (r.size() == 2) { fHodoFirstY[i] = r[0]; fHodoLastY[i] = r[1]; }
    }
  }
}

double TBaux::GetPeakADC(std::vector<short> waveform, int xInit, int xFin, int pedBins) {
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

double TBaux::GetIntADC(std::vector<short> waveform, int xInit, int xFin, int pedBins) {
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

float TBaux::LinearInterp(float x1, float y1, float x2, float y2, float threshold) const {
  return x1 + (threshold - y1) * (x2 - x1) / (y2 - y1);
}

float TBaux::GetLeadingEdgeBin(const std::vector<float>& waveform, float percent) const {

  if (waveform.size() < 1002)
    return -1;

  float max = *std::max_element(waveform.begin() + 1, waveform.begin() + 1001);
  float thr = max * percent;

  for (int i = 1; i < 1000; i++) {
    if (waveform.at(i) < thr && waveform.at(i + 1) > thr) {
      return LinearInterp(static_cast<float>(i), waveform.at(i), static_cast<float>(i + 1), waveform.at(i + 1), thr);
    }
  }
  return -1; // 교차점을 찾지 못했다.
}

std::vector<float> TBaux::GetPosition(const std::vector<std::vector<float>>& wave) {

  if (wave.size() < 3)
    return {};

  auto binToTime = [](float bin) {
    return 800.f * (bin / 1000.f);
  };

  const float wcxBin = GetLeadingEdgeBin(wave.at(0), static_cast<float>(fWCThreshold));
  const float wcyBin = GetLeadingEdgeBin(wave.at(1), static_cast<float>(fWCThreshold));
  const float nimBin = GetLeadingEdgeBin(wave.at(2), static_cast<float>(fWCThreshold));

  if (wcxBin < 0 || wcyBin < 0 || nimBin < 0)
    return {};

  const float wcxTime = binToTime(wcxBin);
  const float wcyTime = binToTime(wcyBin);
  const float nimTime = binToTime(nimBin);

  const float timeDiffX = nimTime - wcxTime;
  const float timeDiffY = nimTime - wcyTime;

  const float posX = static_cast<float>((fWCReference.at(0) - timeDiffX) * fWCCalibration);
  const float posY = static_cast<float>(-1. * (fWCReference.at(1) - timeDiffY) * fWCCalibration);

  return {posX, posY};
}

void TBaux::Fill(TBevt<TBwaveform> anEvent) {

  // WC가 활성화된 경우 위치를 계산한다.
  if (fWCEnabled && fWCPosition) {
    // WC 채널별 pedestal 구간을 적용한다.
    const int pedBinsWCX = PedBinsForChannel("WCX");
    const int pedBinsWCY = PedBinsForChannel("WCY");
    const int pedBinsNIM = PedBinsForChannel("NIM");
    std::vector<std::vector<float>> wcWaves;
    wcWaves.reserve(3);
    wcWaves.push_back(anEvent.GetData(fCID_WCX).pedcorrectedWaveform(pedBinsWCX));
    wcWaves.push_back(anEvent.GetData(fCID_WCY).pedcorrectedWaveform(pedBinsWCY));
    wcWaves.push_back(anEvent.GetData(fCID_NIM).pedcorrectedWaveform(pedBinsNIM));

    const auto posVec = GetPosition(wcWaves);
    if (posVec.size() == 2)
      fWCPosition->Fill(posVec.at(0), posVec.at(1));
  }

  // 호도스코프의 16×16 IntADC와 PeakADC 최댓값을 채운다.
  if (fHodoEnabled)
    FillHodoscope(anEvent);
}

std::vector<float> TBaux::GetHodoscopeRawPosition(TBevt<TBwaveform> anEvent) {

  if (!fHodoEnabled) return {};
  if (fCID_HodoX.size() != 16 || fCID_HodoY.size() != 16) return {};

  // IntADC와 PeakADC에서 가장 밝은 X/Y 섬유를 각각 찾는다.
  std::vector<float> intADC_X(16, 0.f);
  std::vector<float> intADC_Y(16, 0.f);
  std::vector<float> peakADC_X(16, 0.f);
  std::vector<float> peakADC_Y(16, 0.f);

  for (int i = 0; i < 16; ++i) {
    const std::vector<short> wfX = anEvent.GetData(fCID_HodoX[i]).waveform();
    const std::vector<short> wfY = anEvent.GetData(fCID_HodoY[i]).waveform();
    // HX/HY 채널별 pedestal 구간을 적용한다.
    const std::string nameX = "HX" + std::to_string(i + 1);
    const std::string nameY = "HY" + std::to_string(i + 1);
    const int pedBinsX = PedBinsForChannel(nameX);
    const int pedBinsY = PedBinsForChannel(nameY);
    if (wfX.size() > static_cast<size_t>(fHodoLastX[i])) {
      intADC_X[i]  = static_cast<float>(GetIntADC (wfX, fHodoFirstX[i], fHodoLastX[i], pedBinsX));
      peakADC_X[i] = static_cast<float>(GetPeakADC(wfX, fHodoFirstX[i], fHodoLastX[i], pedBinsX));
    }
    if (wfY.size() > static_cast<size_t>(fHodoLastY[i])) {
      intADC_Y[i]  = static_cast<float>(GetIntADC (wfY, fHodoFirstY[i], fHodoLastY[i], pedBinsY));
      peakADC_Y[i] = static_cast<float>(GetPeakADC(wfY, fHodoFirstY[i], fHodoLastY[i], pedBinsY));
    }
  }

  // 채널별 보정 상수로 ADC 값을 정규화한다.
  for (int i = 0; i < 16; ++i) {
    intADC_X[i]  /= static_cast<float>(fHodoNormIntADC_X[i]);
    intADC_Y[i]  /= static_cast<float>(fHodoNormIntADC_Y[i]);
    peakADC_X[i] /= static_cast<float>(fHodoNormPeakADC_X[i]);
    peakADC_Y[i] /= static_cast<float>(fHodoNormPeakADC_Y[i]);
  }

  const int xIdxInt  = std::max_element(intADC_X.begin(),  intADC_X.end())  - intADC_X.begin();
  const int yIdxInt  = std::max_element(intADC_Y.begin(),  intADC_Y.end())  - intADC_Y.begin();
  const int xIdxPeak = std::max_element(peakADC_X.begin(), peakADC_X.end()) - peakADC_X.begin();
  const int yIdxPeak = std::max_element(peakADC_Y.begin(), peakADC_Y.end()) - peakADC_Y.begin();

  // 섬유 bin 중심 좌표를 원시 위치로 사용한다.
  return {
    xIdxInt  + 0.5f, yIdxInt  + 0.5f,
    xIdxPeak + 0.5f, yIdxPeak + 0.5f,
  };
}

void TBaux::FillHodoscope(TBevt<TBwaveform> anEvent) {

  if (!fHodoIntADC || !fHodoPeakADC) return;

  const auto raw = GetHodoscopeRawPosition(anEvent);
  if (raw.size() != 4) return;

  const float rawX_int  = raw[0];
  const float rawY_int  = raw[1];
  const float rawX_peak = raw[2];
  const float rawY_peak = raw[3];

  // 설정 중심을 기준으로 명목 중심 (8, 8)에 맞춘다.
  const float corrX_int  = rawX_int  - fHodoCenter[0] + 8.0f;
  const float corrY_int  = rawY_int  - fHodoCenter[1] + 8.0f;
  const float corrX_peak = rawX_peak - fHodoCenter[0] + 8.0f;
  const float corrY_peak = rawY_peak - fHodoCenter[1] + 8.0f;

  fHodoIntADC      ->Fill(rawX_int,   rawY_int,   1);
  fHodoPeakADC     ->Fill(rawX_peak,  rawY_peak,  1);
  if (fHodoIntADC_corr ) fHodoIntADC_corr ->Fill(corrX_int,  corrY_int,  1);
  if (fHodoPeakADC_corr) fHodoPeakADC_corr->Fill(corrX_peak, corrY_peak, 1);
}

bool TBaux::IsPassing(TBevt<TBwaveform> anEvent) {

  // WC 매핑이 없으면 AUX 컷을 적용하지 않는다.
  if (!fWCEnabled) return true;

  // 중심 보정된 WC 빔 위치 컷을 적용한다.
  const int pedBinsWCX = PedBinsForChannel("WCX");
  const int pedBinsWCY = PedBinsForChannel("WCY");
  const int pedBinsNIM = PedBinsForChannel("NIM");
  std::vector<std::vector<float>> wcWaves;
  wcWaves.reserve(3);
  wcWaves.push_back(anEvent.GetData(fCID_WCX).pedcorrectedWaveform(pedBinsWCX));
  wcWaves.push_back(anEvent.GetData(fCID_WCY).pedcorrectedWaveform(pedBinsWCY));
  wcWaves.push_back(anEvent.GetData(fCID_NIM).pedcorrectedWaveform(pedBinsNIM));

  auto posVec = GetPosition(wcWaves); // X, Y in mm
  if (posVec.size() != 2)
    return false;

  if (fWCPosCut > 0) {
    if (std::abs(posVec.at(0)) > fWCPosCut)
      return false;
    if (std::abs(posVec.at(1)) > fWCPosCut)
      return false;
  }

  // WCHodo 모드에서는 보정 중심 기준의 장비 간 기울기 컷도 적용한다.
  if (fAuxCutMode == "WCHodo") {
    const auto hodoRaw = GetHodoscopeRawPosition(anEvent);
    if (hodoRaw.size() != 4)
      return false;  // 호도스코프 정보가 없으면 통과시키지 않는다.

    // 설정에 따라 IntADC 또는 PeakADC 위치를 컷에 사용한다.
    const bool usePeak = (fHodoCutMethod == "PeakADC");
    const float hodo_x_raw = usePeak ? hodoRaw[2] : hodoRaw[0];
    const float hodo_y_raw = usePeak ? hodoRaw[3] : hodoRaw[1];
    const float hodo_x_centered = hodo_x_raw - static_cast<float>(fHodoCenter[0]);
    const float hodo_y_centered = hodo_y_raw - static_cast<float>(fHodoCenter[1]);

    const float dx = posVec.at(0) - hodo_x_centered;
    const float dy = posVec.at(1) - hodo_y_centered;

    if (std::abs(dx) > fInclinationCut[0]) return false;
    if (std::abs(dy) > fInclinationCut[1]) return false;
  }

  return true;
}

void TBaux::Draw() {

  // WC가 있으면 해당 캔버스만 그린다.
  if (!fCanvas || !fWCPosition)
    return;

  fCanvas->cd(1);
  fWCPosition->Draw("colz");

  gSystem->Sleep(1000);
}

void TBaux::SetMaximum() {

}

void TBaux::Update() {

  // 활성화된 AUX 장비가 없으면 갱신하지 않는다.
  const bool hasWC   = fWCEnabled && fCanvas && fWCPosition;
  const bool hasHodo = fHodoEnabled && fCanvasHodoIntADC && fHodoIntADC;
  if (!hasWC && !hasHodo)
    return;

  if (fIsFirst) fIsFirst = false;

  SetMaximum();

  // 활성화된 AUX 캔버스를 모두 그린다.
  if (hasWC) {
    fCanvas->cd(1);
    fWCPosition->Draw("colz");
    fCanvas->cd();
    fCanvas->Update();
    if (fDraw) fCanvas->Pad()->Draw();
  }

  if (fHodoEnabled && fCanvasHodoIntADC && fHodoIntADC) {
    fCanvasHodoIntADC->cd();
    fHodoIntADC->Draw("colz");
    fCanvasHodoIntADC->Update();
    if (fDraw) fCanvasHodoIntADC->Pad()->Draw();
  }

  if (fHodoEnabled && fCanvasHodoPeakADC && fHodoPeakADC) {
    fCanvasHodoPeakADC->cd();
    fHodoPeakADC->Draw("colz");
    fCanvasHodoPeakADC->Update();
    if (fDraw) fCanvasHodoPeakADC->Pad()->Draw();
  }

  if (fHodoEnabled && fCanvasHodoIntADC_corr && fHodoIntADC_corr) {
    fCanvasHodoIntADC_corr->cd();
    fHodoIntADC_corr->Draw("colz");
    fCanvasHodoIntADC_corr->Update();
    if (fDraw) fCanvasHodoIntADC_corr->Pad()->Draw();
  }

  if (fHodoEnabled && fCanvasHodoPeakADC_corr && fHodoPeakADC_corr) {
    fCanvasHodoPeakADC_corr->cd();
    fHodoPeakADC_corr->Draw("colz");
    fCanvasHodoPeakADC_corr->Update();
    if (fDraw) fCanvasHodoPeakADC_corr->Pad()->Draw();
  }

  // 활성화된 WC·호도스코프 객체를 하나의 ROOT 파일에 기록한다.
  TString output = "./output/Run" + std::to_string(fRunNum) + "_AUX.root";
  if (fAuxCut) output = "./output/Run" + std::to_string(fRunNum) + "_AUX_AuxCut.root";
  {
    TFile outoutFile(output, "RECREATE");
    outoutFile.cd();
    if (hasWC) {
      fCanvas->Write();
      fWCPosition->Write();
    }
    if (fHodoEnabled) {
      if (fCanvasHodoIntADC)       fCanvasHodoIntADC      ->Write();
      if (fCanvasHodoPeakADC)      fCanvasHodoPeakADC     ->Write();
      if (fCanvasHodoIntADC_corr)  fCanvasHodoIntADC_corr ->Write();
      if (fCanvasHodoPeakADC_corr) fCanvasHodoPeakADC_corr->Write();
      if (fHodoIntADC)             fHodoIntADC      ->Write();
      if (fHodoPeakADC)            fHodoPeakADC     ->Write();
      if (fHodoIntADC_corr)        fHodoIntADC_corr ->Write();
      if (fHodoPeakADC_corr)       fHodoPeakADC_corr->Write();
    }
    outoutFile.Close();
  }

  // DRAW 모드에서만 GUI 이벤트를 처리한다.
  if (fDraw) gSystem->ProcessEvents();

  gSystem->Sleep(1000);
}

void TBaux::SaveAs(TString output) {

  if (output == "")
    output = "./output/Run" + std::to_string(fRunNum) + "_AUX.root";

  // 저장할 AUX 객체가 없으면 종료한다.
  if (!fWCPosition && !fHodoIntADC)
    return;

  TFile* outoutFile = new TFile(output, "RECREATE");
  outoutFile->cd();

  if (fWCPosition) fWCPosition->Write();
  if (fHodoEnabled) {
    if (fHodoIntADC)       fHodoIntADC      ->Write();
    if (fHodoPeakADC)      fHodoPeakADC     ->Write();
    if (fHodoIntADC_corr)  fHodoIntADC_corr ->Write();
    if (fHodoPeakADC_corr) fHodoPeakADC_corr->Write();
  }

  outoutFile->Close();
}
