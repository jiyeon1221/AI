// ─────────────────────────────────────────────────────────────────────────────
//  normalize_hodo.cc
//
//  Per-channel IntADC normalization for the 16+16 hodoscope fibers.
//
//  What it does
//  ------------
//  For every hodoscope channel HX1..HX16 / HY1..HY16:
//    1. Computes IntADC per event over a user-defined integration window
//       (kIntFirst, kIntLast) — same convention as draw_hodoscope.cc.
//    2. Accumulates a per-channel IntADC distribution (1D histogram).
//    3. Takes the histogram's MEAN as the channel's normalization constant.
//
//        norm_const[ch] = mean[ch]      // mean of channel ch's IntADC dist.
//
//  Downstream code applies it as:
//        IntADC_calibrated[ch] = IntADC_raw[ch] / norm_const[ch]
//  After this, every calibrated channel's IntADC distribution is centered
//  near 1.0 — i.e., per-channel response is equalized. The absolute ADC
//  scale is intentionally dropped (each channel is normalized against its
//  OWN mean, not a global one), so downstream code that needs an absolute
//  charge should keep using the raw IntADC.
//
//  Outputs (under ./Hodoscope/):
//    hodo_norm_intADC.root   — 32 TH1F distributions, for QA
//    hodo_norm_intADC.txt    — plain-text table with constants
//  These filenames are FIXED (not per-run) because the calibration is done
//  once for the entire beam test period. The run number used for calibration
//  is recorded inside the file headers for provenance.
//
//  Usage
//  -----
//    ./normalize_hodo <RunNumber> [MaxEvent]
//        MaxEvent defaults to 30000 (matches the team's recommended sample).
//        Pass -1 to use every available event in the run.
//
//  Notes
//  -----
//  - This is a SEPARATE pass from draw_hodoscope.cc on purpose: it's run once
//    per calibration run, the resulting *.txt is then read by any downstream
//    code that wants equalized hodoscope signals.
//  - The integration range below (kIntFirst, kIntLast) is intentionally
//    hardcoded — change it per beam condition. The reference team's workflow
//    is: (a) run jbnu_daq_calib.C to LOCATE the average-waveform peak, (b)
//    pick an integration window around it, then (c) feed that window into a
//    normalization pass (this script).
// ─────────────────────────────────────────────────────────────────────────────

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
  // TBplotengine 1D distributions, so cross-comparison is easy if you ever
  // overlay them.
  std::vector<TH1F*> hIntADC(kNChannels, nullptr);
  for (int i = 0; i < kNChannels; ++i) {
    const std::string name = "h_" + ChannelName(i) + "_intADC";
    const std::string title = ChannelName(i) + " IntADC;IntADC;events";
    hIntADC[i] = new TH1F(name.c_str(), title.c_str(), 440, -30000., 300000.);
  }

  // ── Read events ───────────────────────────────────────────────────────────
  // MID list {8, 9} mirrors draw_hodoscope.cc; the hodoscope is split across
  // MID 8 (X-fibers) and MID 9 (Y-fibers) in the KEK setup.
  // MIDs
  // 1: PMT C
  // 2: PMT S + trg
  // 8, 9, 11: MCP S
  // 11, 13, 15: MCP C
  // 16: WC, NIM
  // 17: Hodo X, Y
  TBread<TBwaveform> reader =
      TBread<TBwaveform>(fRunNum, fMaxEvent, -1, false,
                         "/u/user/swkim/SE_UserHome/2025_KEK_TB_Data", {17});

  if (fMaxEvent == -1 || fMaxEvent > reader.GetMaxEvent())
    fMaxEvent = reader.GetMaxEvent();

  std::cout << "[normalize_hodo] Run " << fRunNum << ", MaxEvent = " << fMaxEvent
            << ", integration window = [" << kIntFirst << ", " << kIntLast << ")"
            << std::endl;

  // ── Event loop: per channel, GetInt(waveform, kIntFirst, kIntLast) ────────
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

  // ── Compute per-channel mean (= normalization constant) ───────────────────
  // We use the histogram's GetMean() (so only events that fell inside the
  // histogram range contribute). For channels that ended up with zero entries
  // (e.g. mapping missing, or DAQ dropout) we emit norm_const = 1.0 so
  // downstream code is safe to divide by it.
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

  // ── Normalization constants ───────────────────────────────────────────────
  // norm_const[ch] = mean[ch]     (each channel divides by its OWN mean)
  //   -> downstream: IntADC_calibrated = IntADC_raw / norm_const[ch]
  //   -> after calibration every channel's IntADC distribution is centered
  //      around 1.0, so per-channel response is equalized.
  // Channels with no data are left at 1.0 so a downstream blind divide is a
  // no-op rather than producing inf/NaN.
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
