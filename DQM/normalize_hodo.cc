// HX/HY 32개 섬유의 평균 IntADC를 정규화 상수로 저장한다.
// 사용법: ./normalize_hodo <RunNumber> [MaxEvent]

#include "TBread.h"
#include "TButility.h"
#include "function.h"

#include "TH1.h"
#include "TFile.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

// ── User-tunable: integration window for IntADC ─────────────────────────────
// Same convention as draw_hodoscope.cc: bins [kIntFirst, kIntLast) of the
// waveform are integrated after pedestal subtraction (GetInt() from function.h).
constexpr int kIntFirst = 135;
constexpr int kIntLast  = 270;

// ── Defaults ────────────────────────────────────────────────────────────────
constexpr int kDefaultMaxEvent = 30000;

// ── Hodoscope channel naming ────────────────────────────────────────────────
// 16 X-fibers (HX1..HX16) + 16 Y-fibers (HY1..HY16) = 32 channels total. The
// ordering matches what TButility::GetCID() looks up via the mapping file.
constexpr int kNFibers = 16;
constexpr int kNChannels = 2 * kNFibers;

// Returns "HX<n>" or "HY<n>" for index 0..31. First 16 are X, next 16 are Y.
std::string ChannelName(int idx) {
  const bool isY = (idx >= kNFibers);
  const int n = (isY ? idx - kNFibers : idx) + 1;
  return std::string(isY ? "HY" : "HX") + std::to_string(n);
}

} // namespace

int main(int argc, char* argv[]) {
  if (argc < 2) {
    std::cerr << "Usage: " << argv[0] << " <RunNumber> [MaxEvent=" << kDefaultMaxEvent << "]\n"
              << "       MaxEvent = -1 uses every available event.\n";
    return 1;
  }

  const int fRunNum  = std::stoi(argv[1]);
  int fMaxEvent      = (argc >= 3) ? std::stoi(argv[2]) : kDefaultMaxEvent;

  // ── Output directory ──────────────────────────────────────────────────────
  fs::path outDir("./Hodoscope");
  if (!fs::exists(outDir)) fs::create_directory(outDir);

  // ── Mapping (same path as draw_hodoscope.cc) ──────────────────────────────
  // Channel names (HX<n>, HY<n>) → (mid, ch) come from this ROOT mapping file.
  TButility util;
  util.LoadMapping("../mapping/mapping_KEK.root");

  // ── Resolve CIDs and skip channels missing from the mapping ───────────────
  // Missing channels would later throw out_of_range when GetData() is called
  // on an invalid CID, so filter them once up-front and warn the user.
  std::vector<TBcid> cids(kNChannels);
  std::vector<bool> valid(kNChannels, false);
  for (int i = 0; i < kNChannels; ++i) {
    cids[i] = util.GetCID(ChannelName(i));
    valid[i] = (cids[i].mid() != -1 && cids[i].channel() != -1);
    if (!valid[i]) {
      std::cerr << "[normalize_hodo] WARNING: channel '" << ChannelName(i)
                << "' not found in mapping; it will be skipped (norm_const = 1.0).\n";
    }
  }

  // ── Per-channel IntADC distributions ──────────────────────────────────────
  // 440 bins from -30000 to 300000 matches the binning used by the existing
  // 채널별 IntADC 분포.
  std::vector<TH1F*> hIntADC(kNChannels, nullptr);
  for (int i = 0; i < kNChannels; ++i) {
    const std::string name = "h_" + ChannelName(i) + "_intADC";
    const std::string title = ChannelName(i) + " IntADC;IntADC;events";
    hIntADC[i] = new TH1F(name.c_str(), title.c_str(), 440, -30000., 300000.);
  }

  // MID 17의 Hodoscope X·Y 파형을 읽는다.
  TBread<TBwaveform> reader =
      TBread<TBwaveform>(fRunNum, fMaxEvent, -1, false,
                         "/u/user/swkim/SE_UserHome/2025_KEK_TB_Data", {17});

  if (fMaxEvent == -1 || fMaxEvent > reader.GetMaxEvent())
    fMaxEvent = reader.GetMaxEvent();

  std::cout << "[normalize_hodo] Run " << fRunNum << ", MaxEvent = " << fMaxEvent
            << ", integration window = [" << kIntFirst << ", " << kIntLast << ")"
            << std::endl;

  // 이벤트별 채널 IntADC를 누적한다.
  for (int iEvt = 0; iEvt < fMaxEvent; ++iEvt) {
    if (iEvt % 1000 == 0) printProgress(iEvt, fMaxEvent);

    TBevt<TBwaveform> anEvt = reader.GetAnEvent();

    for (int i = 0; i < kNChannels; ++i) {
      if (!valid[i]) continue;
      const auto wave = anEvt.GetData(cids[i]).waveform();
      const double iadc = GetInt(wave, kIntFirst, kIntLast);
      hIntADC[i]->Fill(iadc);
    }
  }
  std::cout << std::endl;

  // 채널별 평균과 RMS를 계산한다.
  std::vector<double> mean(kNChannels, 0.0);
  std::vector<double> rms (kNChannels, 0.0);
  std::vector<long>   N   (kNChannels, 0);
  int nGood = 0;
  for (int i = 0; i < kNChannels; ++i) {
    if (!valid[i] || hIntADC[i]->GetEntries() == 0) continue;
    mean[i] = hIntADC[i]->GetMean();
    rms[i]  = hIntADC[i]->GetRMS();
    N[i]    = (long)hIntADC[i]->GetEntries();
    ++nGood;
  }

  if (nGood == 0) {
    std::cerr << "[normalize_hodo] ERROR: no valid channels with entries; "
              << "aborting.\n";
    return 2;
  }

  // 채널 평균을 정규화 상수로 사용하며 데이터가 없으면 1.0을 유지한다.
  std::vector<double> normConst(kNChannels, 1.0);
  for (int i = 0; i < kNChannels; ++i) {
    if (!valid[i] || mean[i] == 0.0) {
      normConst[i] = 1.0;
      continue;
    }
    normConst[i] = mean[i];
  }

  // ── Write ROOT file with the 32 distributions (for QA) ────────────────────
  // A single calibration file is produced for the entire beam test period —
  // run number is recorded in the header for provenance but the filename is
  // fixed so downstream code can load it without knowing which run was used.
  const std::string rootPath = "./Hodoscope/hodo_norm_intADC.root";
  TFile* outRoot = new TFile(rootPath.c_str(), "RECREATE");
  outRoot->cd();
  for (int i = 0; i < kNChannels; ++i) {
    if (hIntADC[i]) hIntADC[i]->Write();
  }
  outRoot->Close();
  delete outRoot;

  // ── Write plain-text table of constants ───────────────────────────────────
  // Format: <channel> <entries> <mean> <rms> <norm_const>
  // First few lines are comments (#) so the file is easy to grep/awk/read.
  const std::string txtPath = "./Hodoscope/hodo_norm_intADC.txt";
  std::ofstream out(txtPath);
  if (!out) {
    std::cerr << "[normalize_hodo] ERROR: cannot open " << txtPath << " for writing.\n";
    return 3;
  }

  out << "# Hodoscope IntADC normalization constants -- Run " << fRunNum << "\n";
  out << "# Generated from up to " << fMaxEvent << " events; integration window ["
      << kIntFirst << ", " << kIntLast << ").\n";
  out << "# Good (with-data) channels: " << nGood << " / " << kNChannels << "\n";
  out << "# norm_const[ch] = mean of channel ch's IntADC distribution\n";
  out << "# Usage: IntADC_calibrated[ch] = IntADC_raw[ch] / norm_const[ch]\n";
  out << "#        -> after calibration each channel's IntADC distribution\n";
  out << "#           is centered near 1.0 (per-channel response equalized).\n";
  out << "#\n";
  out << "# " << std::left << std::setw(6)  << "ch"
              << std::right << std::setw(10) << "entries"
              << std::right << std::setw(14) << "mean"
              << std::right << std::setw(14) << "rms"
              << std::right << std::setw(14) << "norm_const"
              << "\n";
  out << std::fixed << std::setprecision(6);
  for (int i = 0; i < kNChannels; ++i) {
    out << "  " << std::left << std::setw(6)  << ChannelName(i)
                << std::right << std::setw(10) << N[i]
                << std::right << std::setw(14) << std::setprecision(2) << mean[i]
                << std::right << std::setw(14) << std::setprecision(2) << rms[i]
                << std::right << std::setw(14) << std::setprecision(6) << normConst[i]
                << "\n";
  }
  out.close();

  // ── Console summary ───────────────────────────────────────────────────────
  // Report min/max over good channels only so a leftover 1.0 from a missing
  // channel doesn't squash the range and hide real spread.
  double minGood = 0.0, maxGood = 0.0;
  bool firstGood = true;
  for (int i = 0; i < kNChannels; ++i) {
    if (!valid[i] || mean[i] == 0.0) continue;
    if (firstGood) { minGood = maxGood = normConst[i]; firstGood = false; continue; }
    minGood = std::min(minGood, normConst[i]);
    maxGood = std::max(maxGood, normConst[i]);
  }

  std::cout << "[normalize_hodo] Wrote " << rootPath << "\n";
  std::cout << "[normalize_hodo] Wrote " << txtPath << "\n";
  std::cout << "[normalize_hodo] Good channels: " << nGood << " / " << kNChannels << "\n";
  std::cout << "[normalize_hodo] norm_const (= per-channel mean) range: ["
            << std::fixed << std::setprecision(2)
            << minGood << ", " << maxGood << "]\n";

  return 0;
}
