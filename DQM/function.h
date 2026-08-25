// Utility functions for DAQ waveform analysis and DWC position calculation.

#ifndef FUNCTION_H
#define FUNCTION_H

#include <stdexcept>
#include <stdio.h>
#include <stdlib.h>
#include <iostream>
#include <string>
#include <numeric>    // For std::accumulate
#include <algorithm>  // For std::min_element, std::max_element
#include <map>
#include <vector>

#include "TROOT.h"
#include "TStyle.h"
#include <TChain.h>
#include <TFile.h>
#include <TTree.h>
#include <TF1.h>
#include <TH1D.h>
#include <TH2D.h>
#include <TCanvas.h>

//////////////////////////////////////////////////////////////////////////////
// VISUALIZATION UTILITIES
//////////////////////////////////////////////////////////////////////////////

// Standard color palette for ROOT histograms.
std::vector<int> myColorPalette {
  1,   // kBlack
  2,   // kRed  
  4,   // kBlue
  417, // kGreen+1
  616, // kMagenta
  433, // kAzure+3
  807, // kOrange+7
  399, // kYellow-1
  429  // kCyan+1
};

//////////////////////////////////////////////////////////////////////////////
// Full width half maximum (FWHM) calculation
//////////////////////////////////////////////////////////////////////////////

// Calculate FWHM, and get the center position of the FWHM
// Use TH1 smooth function to reduce fluctuation of the peak position, left and right edge
// Use interpolation to get the precise position of the FWHM
float GetFWHM(const TH1* h, float& xCenter)
{
    TH1F* h_smooth = (TH1F*) h->Clone();
    h_smooth->Smooth(1, "R");
    const int maxBin = h_smooth->GetMaximumBin();
    const float maxVal = h_smooth->GetBinContent(maxBin);
    if (maxVal <= 0.) { xCenter = std::numeric_limits<float>::quiet_NaN(); return 0.; }

    const float halfMax = 0.5 * maxVal;
    int leftBin = maxBin, rightBin = maxBin;

    while (leftBin > 1 && h_smooth->GetBinContent(leftBin) > halfMax) --leftBin;
    while (rightBin < h_smooth->GetNbinsX() && h_smooth->GetBinContent(rightBin) > halfMax) ++rightBin;

    auto interpolate = [&](int bin1, int bin2) {
        float y1 = h_smooth->GetBinContent(bin1);
        float y2 = h_smooth->GetBinContent(bin2);
        float x1 = h_smooth->GetBinCenter(bin1);
        float x2 = h_smooth->GetBinCenter(bin2);
        return (y2 == y1) ? x1 : x1 + (halfMax - y1) * (x2 - x1) / (y2 - y1);
    };

    const float xLeft = interpolate(leftBin, leftBin + 1);
    const float xRight = interpolate(rightBin, rightBin - 1);

    xCenter = 0.5 * (xLeft + xRight);
    return xRight - xLeft;
}

// Calculate width at a given fraction of the maximum value, and get the center position of the width
// Use TH1 smooth function to reduce fluctuation of the peak position, left and right edge
// Use interpolation to get the precise position of the width
// fraction = 0.5 -> FWHM, 0.1 -> 10% width, 0.9 -> 90% width etc.
float GetWidthAtFraction(const TH1* h, float& xCenter, float fraction = 0.5)
{
  TH1F* h_smooth = (TH1F*) h->Clone();
  h_smooth->Smooth(1, "R");
  const int maxBin = h_smooth->GetMaximumBin();
  const float maxVal = h_smooth->GetBinContent(maxBin);
  if (maxVal <= 0.) { xCenter = std::numeric_limits<float>::quiet_NaN(); return 0.; }

  const float halfMax = fraction * maxVal;
  int leftBin = maxBin, rightBin = maxBin;

  while (leftBin > 1 && h_smooth->GetBinContent(leftBin) > halfMax) --leftBin;
  while (rightBin < h_smooth->GetNbinsX() && h_smooth->GetBinContent(rightBin) > halfMax) ++rightBin;

  auto interpolate = [&](int bin1, int bin2) {
      float y1 = h_smooth->GetBinContent(bin1);
      float y2 = h_smooth->GetBinContent(bin2);
      float x1 = h_smooth->GetBinCenter(bin1);
      float x2 = h_smooth->GetBinCenter(bin2);
      return (y2 == y1) ? x1 : x1 + (halfMax - y1) * (x2 - x1) / (y2 - y1);
  };

  const float xLeft = interpolate(leftBin, leftBin + 1);
  const float xRight = interpolate(rightBin, rightBin - 1);

  xCenter = 0.5 * (xLeft + xRight);
  return xRight - xLeft;
}

//////////////////////////////////////////////////////////////////////////////
// PEDESTAL CALCULATION FUNCTIONS
//////////////////////////////////////////////////////////////////////////////

// Calculate pedestal (baseline) from beginning of waveform.
float getPed(std::vector<short> waveform) {
  return std::accumulate( waveform.begin() + 1, waveform.begin() + 101, 0.) / 100.;
}

// Calculate pedestal from end of waveform (alternative method).
float getPedfromBack(std::vector<short> waveform) {
  return std::accumulate( waveform.end() - 124, waveform.end() - 24, 0.) / 100.;
}

//////////////////////////////////////////////////////////////////////////////
// MINIMUM FINDING FUNCTIONS (PEAK DETECTION)
//////////////////////////////////////////////////////////////////////////////

// Find minimum ADC value in waveform (raw peak detection).
float getMin(std::vector<short> waveform) {
  return *(std::min_element(waveform.begin() + 1, waveform.end() - 23));
}

// Find minimum ADC value within specified range.
float getMinFrom(std::vector<short> waveform, int from, int end) {
  int minus = waveform.size() - end;
  return *(std::min_element(waveform.begin() + from, waveform.end() - minus));
}

// Get bin index of minimum ADC value (peak position).
int getMinIdx(std::vector<short> waveform) {
  return std::distance( waveform.begin(), std::min_element(waveform.begin() + 1, waveform.end() - 23) );
}

// Get bin index of minimum value within specified range.
int getMinIdxFrom(std::vector<short> waveform, int from, int end) {
  int minus = waveform.size() - end;
  return std::distance( waveform.begin(), std::min_element(waveform.begin() + from, waveform.end() - minus) );
}

//////////////////////////////////////////////////////////////////////////////
// INTERPOLATION AND TIMING FUNCTIONS
//////////////////////////////////////////////////////////////////////////////

// Perform linear interpolation between two points.
double linearInterpolation(double x1, double y1, double x2, double y2, double threshold) {
    return x1 + (threshold - y1) * (x2 - x1) / (y2 - y1);
}

// Interpolate precise threshold crossing bin for timing analysis.
float interpolate(std::vector<short> waveform, int thrs_bin, float thrs) {
  float x0 = (float) (thrs_bin - 1);
  float x1 = (float) thrs_bin;
  float y0 = (float) getPed(waveform) - waveform.at(thrs_bin-1);
  float y1 = (float) getPed(waveform) - waveform.at(thrs_bin);

  return (float)( x0 + (thrs - y0) * (x1 - x0) / (y1 - y0) );
}

//////////////////////////////////////////////////////////////////////////////
// WAVEFORM PROCESSING FUNCTIONS
//////////////////////////////////////////////////////////////////////////////

// Scale waveform for average time structure calculation.
std::vector<float> GetAvg(std::vector<short> waveform, int maxEntry)
{
  std::vector<float> scaled_waveform;
  for(int i = 0; i < waveform.size(); i++)
    scaled_waveform.push_back( ( (float) waveform.at(i) / (float) maxEntry) );
  return scaled_waveform;
}

//////////////////////////////////////////////////////////////////////////////
// SIGNAL INTEGRATION FUNCTIONS
//////////////////////////////////////////////////////////////////////////////

// Calculate integrated ADC with automatic pedestal correction.
double GetInt(std::vector<short> waveform, int startBin, int endBin)
{
  double ped = getPed(waveform);
  std::vector<double> pedCorrectedWave;
  for (int i = 0; i < waveform.size(); i++)
    pedCorrectedWave.push_back(ped - waveform.at(i));

  return (std::accumulate(pedCorrectedWave.begin() + startBin, pedCorrectedWave.begin() + endBin, 0.));
}

//////////////////////////////////////////////////////////////////////////////
// PEAK AMPLITUDE FUNCTIONS  
//////////////////////////////////////////////////////////////////////////////

// Find peak amplitude with automatic pedestal correction.
double GetPeak(std::vector<short> waveform, int startBin, int endBin)
{
  double ped = getPed(waveform);
  
  std::vector<double> pedCorrectedWave;
  for (int i = 0; i < waveform.size(); i++)
    pedCorrectedWave.push_back(ped - (double)waveform.at(i));

  return (*std::max_element(pedCorrectedWave.begin() + startBin, pedCorrectedWave.begin() + endBin));
}

//////////////////////////////////////////////////////////////////////////////
// FUNCTIONS WITH EXTERNAL PEDESTAL
//////////////////////////////////////////////////////////////////////////////

// Calculate integrated ADC using provided pedestal value.
double GetIntWithPed(std::vector<short> waveform, int startBin, int endBin, double ped)
{  
  std::vector<double> pedCorrectedWave;
  for (int i = 0; i < waveform.size(); i++)
    pedCorrectedWave.push_back(ped - (double)waveform.at(i));

  return (std::accumulate(pedCorrectedWave.begin() + startBin, pedCorrectedWave.begin() + endBin, 0.));
}

// Find peak amplitude using provided pedestal value.
double GetPeakWithPed(std::vector<short> waveform, int startBin, int endBin, double ped)
{  
  std::vector<double> pedCorrectedWave;
  for (int i = 0; i < waveform.size(); i++)
    pedCorrectedWave.push_back(ped - (double)waveform.at(i));

  return (*std::max_element(pedCorrectedWave.begin() + startBin, pedCorrectedWave.begin() + endBin));
}


//////////////////////////////////////////////////////////////////////////////
// DWC (DELAYED WIRE CHAMBER) POSITION CALCULATION
//////////////////////////////////////////////////////////////////////////////

// Convert waveform bin index to time in nanoseconds.
double getTime(double bin, double time_window=200.) {
  return time_window * (bin / 1000.);
}

// Get bin index of signal peak (minimum ADC value).
int getPeakBin(std::vector<short> waveform) {
    return ( std::min_element(waveform.begin()+1, waveform.end()-23) - waveform.begin() );
}

// Find leading edge bin at specified threshold fraction.
int getLeadingEdgeBin(std::vector<short> waveform, float threshold, int start, int end) {

    double ped = getPed(waveform);
    std::vector<double> pedCorrWaveform;
    for(int idx = 0; idx < waveform.size(); idx++){
        pedCorrWaveform.emplace_back(ped - (double)waveform.at(idx));
    }

    double max = *max_element(pedCorrWaveform.begin()+start, pedCorrWaveform.begin()+end);
    double thr = max * threshold;

    for (int idx = 1; idx < pedCorrWaveform.size()-23; idx++){
      if (pedCorrWaveform.at(idx) >= thr)
        return idx;
    }
    return -1;
}

// Calculate leading edge time with interpolation (800ns window).
float getLeadingEdgeTime_interpolated800(std::vector<short> waveform, float threshold, int start, int end) {
    
    int leadingEdgeBin = getLeadingEdgeBin(waveform, threshold, start, end);

    float thr = GetPeak(waveform, start, end) * threshold;

    if (leadingEdgeBin == 1)
      return getTime(leadingEdgeBin, 800.);

    float interpolated_bin = interpolate(waveform, leadingEdgeBin, thr);

    return getTime(interpolated_bin, 800.);
}

// Calculate leading edge time with interpolation (200ns window).
float getLeadingEdgeTime_interpolated200(std::vector<short> waveform, float threshold, int start, int end) {
    
    int leadingEdgeBin = getLeadingEdgeBin(waveform, threshold, start, end);

    float thr = GetPeak(waveform, start, end) * threshold;

    if (leadingEdgeBin == 1)
      return getTime(leadingEdgeBin, 200.);

    float interpolated_bin = interpolate(waveform, leadingEdgeBin, thr);

    return getTime(interpolated_bin, 200.);
}

// Calculate leading edge time without interpolation.
float getLeadingEdgeTime_noInterpolation(std::vector<short> waveform, float threshold, int start, int end) {
  int bin = getLeadingEdgeBin(waveform, threshold, start, end);
  return getTime(bin, 800.);
}

// Get peak timing from waveform.
float getPeakTime(std::vector<short> waveform) {
    int peakBin = getPeakBin(waveform);
    return (getTime(peakBin, 800.));
}

//////////////////////////////////////////////////////////////////////////////
// DWC POSITION RECONSTRUCTION FUNCTIONS
//////////////////////////////////////////////////////////////////////////////

// DWC 맞은편 채널의 시간 차이로 보정된 X/Y 위치를 계산한다.

// DWC1 시간값 [Right, Left, Up, Down]을 보정된 [X, Y] mm로 변환한다.
std::vector<float> getDWC1position(std::vector<float> dwc1Time, std::vector<float> dwc1Offset) {
    // TB2025, 2800V, 40% leading-edge 보정값.
    float dwc1_horizontal_Slope  = 0.180654;
    float dwc1_horizontal_Offset = 0.217961;
    float dwc1_Vertical_Slope    = -0.180342;
    float dwc1_Vertical_Offset   = -0.0994697;

    std::vector<float> dwc1Position;

    // 시간 차이에 기울기와 오프셋 보정을 적용한다.
    float horizontalPos = ((float)(dwc1Time.at(0) - dwc1Time.at(1)) * dwc1_horizontal_Slope) 
                         + dwc1_horizontal_Offset - dwc1Offset.at(0);
    float verticalPos = ((float)(dwc1Time.at(2) - dwc1Time.at(3)) * dwc1_Vertical_Slope) 
                       + dwc1_Vertical_Offset - dwc1Offset.at(1);

    dwc1Position.push_back(horizontalPos);
    dwc1Position.push_back(verticalPos);

    return dwc1Position;
}

// DWC2 시간값 [Right, Left, Up, Down]을 보정된 [X, Y] mm로 변환한다.
std::vector<float> getDWC2position(std::vector<float> dwc2Time, std::vector<float> dwc2Offset) {
    // TB2025, 2800V, 40% leading-edge 보정값.
    float dwc2_horizontal_Slope  = 0.181416;
    float dwc2_horizontal_Offset = -0.00911072;
    float dwc2_Vertical_Slope    = -0.17822;
    float dwc2_Vertical_Offset   = -0.0489771;

    std::vector<float> dwc2Position;

    float horizontalPos = ((float)(dwc2Time.at(0) - dwc2Time.at(1)) * dwc2_horizontal_Slope) 
                         + dwc2_horizontal_Offset - dwc2Offset.at(0);
    float verticalPos = ((float)(dwc2Time.at(2) - dwc2Time.at(3)) * dwc2_Vertical_Slope) 
                       + dwc2_Vertical_Offset - dwc2Offset.at(1);

    dwc2Position.push_back(horizontalPos);
    dwc2Position.push_back(verticalPos);

    return dwc2Position;
}

// 빠른 수집 모드의 클록값으로 DWC 위치를 계산한다.
std::vector<float> getDWC1positionUsingClock(std::vector<float> dwc1Time) {
    // TB2025, 2800V, 40% leading-edge 보정값.
    float dwc1_horizontal_Slope  = 0.180654;
    float dwc1_horizontal_Offset = 0.217961;
    float dwc1_Vertical_Slope    = -0.180342;
    float dwc1_Vertical_Offset   = -0.0994697;

    std::vector<float> dwc1Position;

    // 클록을 ns로 바꾼 뒤 좌표 보정을 적용한다.
    float horizontalPos = -( ( (float)(dwc1Time.at(0) - dwc1Time.at(1)) * 25. / 1000. * dwc1_horizontal_Slope ) + dwc1_horizontal_Offset );
    float verticalPos = ( (float)(dwc1Time.at(2) - dwc1Time.at(3)) * 25. / 1000. * dwc1_Vertical_Slope ) + dwc1_Vertical_Offset;

    dwc1Position.push_back(horizontalPos);
    dwc1Position.push_back(verticalPos);

    return dwc1Position;
}

// DWC2 클록값 [Right, Left, Up, Down]을 [X, Y] mm로 변환한다.
std::vector<float> getDWC2positionUsingClock(std::vector<float> dwc2Time) {
    // TB2025, 2800V, 40% leading-edge 보정값.
    float dwc2_horizontal_Slope  = 0.181416;
    float dwc2_horizontal_Offset = -0.00911072;
    float dwc2_Vertical_Slope    = -0.17822;
    float dwc2_Vertical_Offset   = -0.0489771;

    std::vector<float> dwc2Position;

    float horizontalPos = -( ( (float)(dwc2Time.at(0) - dwc2Time.at(1)) * 25. / 1000. * dwc2_horizontal_Slope ) + dwc2_horizontal_Offset );
    float verticalPos = ( (float)(dwc2Time.at(2) - dwc2Time.at(3)) * 25. / 1000. * dwc2_Vertical_Slope ) + dwc2_Vertical_Offset;

    dwc2Position.push_back(horizontalPos);
    dwc2Position.push_back(verticalPos);

    return dwc2Position;
}

// Extract position offset corrections from DWC histogram.
std::vector<float> getDWCoffset(TH2D* dwcHist) {
    float xOffset = dwcHist->GetMean(1);  // Mean of X-axis (axis 1)
    float yOffset = dwcHist->GetMean(2);  // Mean of Y-axis (axis 2)

    std::vector<float> dwcOffset;
    dwcOffset.push_back(xOffset);
    dwcOffset.push_back(yOffset);

    return dwcOffset;
}

//////////////////////////////////////////////////////////////////////////////
// PARTICLE IDENTIFICATION (PID) FUNCTIONS
//////////////////////////////////////////////////////////////////////////////

// Apply DWC correlation cut for particle tracking.
bool dwcCorrelationCut(std::vector<float> dwc1_correctedPosition, std::vector<float> dwc2_correctedPosition, float threshold = 1.5f) {
    bool passed = false;

    float x_diff = std::abs( dwc1_correctedPosition.at(0) - dwc2_correctedPosition.at(0) );
    float y_diff = std::abs( dwc1_correctedPosition.at(1) - dwc2_correctedPosition.at(1) );

    if ( (x_diff <= threshold) && (y_diff <= threshold) ) passed = true;

    return passed;
}

//////////////////////////////////////////////////////////////////////////////
// UTILITY FUNCTIONS
//////////////////////////////////////////////////////////////////////////////

// Display progress bar for long-running analysis.
void printProgress(const int currentStep, const int totalStep)
{
    float progress = (float)currentStep / totalStep;
    int barWidth = 70;
    std::cout << "[";
    int pos = barWidth * progress;
    for (int i = 0; i < barWidth; i++)
    {
        if (i < pos)
            std::cout << "=";
        else if (i == pos)
            std::cout << ">";
        else
            std::cout << " ";
    }
    std::cout << "]  " << currentStep << "/" << totalStep << "  " << int(progress * 100.0) << "%\r";
    std::cout.flush();
}


//////////////////////////////////////////////////////////////////////////////
// DAQ CONFIGURATION MAPPING
//////////////////////////////////////////////////////////////////////////////

// Create mapping between MID-Channel strings and module-channel pairs.
std::map<std::string, std::vector<int>> getModuleConfigMap() {
    std::map<std::string, std::vector<int>> map_btw_MIDCH_and_Name;

    // Generate mapping for all 20 MIDs, each with 32 channels
    for(int i = 1; i <= 20; i++) {
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"01",  std::vector<int>  {i, 1}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"02",  std::vector<int>  {i, 2}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"03",  std::vector<int>  {i, 3}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"04",  std::vector<int>  {i, 4}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"05",  std::vector<int>  {i, 5}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"06",  std::vector<int>  {i, 6}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"07",  std::vector<int>  {i, 7}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"08",  std::vector<int>  {i, 8}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"09",  std::vector<int>  {i, 9}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"10",  std::vector<int>  {i, 10}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"11",  std::vector<int>  {i, 11}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"12",  std::vector<int>  {i, 12}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"13",  std::vector<int>  {i, 13}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"14",  std::vector<int>  {i, 14}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"15",  std::vector<int>  {i, 15}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"16",  std::vector<int>  {i, 16}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"17",  std::vector<int>  {i, 17}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"18",  std::vector<int>  {i, 18}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"19",  std::vector<int>  {i, 19}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"20",  std::vector<int>  {i, 20}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"21",  std::vector<int>  {i, 21}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"22",  std::vector<int>  {i, 22}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"23",  std::vector<int>  {i, 23}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"24",  std::vector<int>  {i, 24}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"25",  std::vector<int>  {i, 25}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"26",  std::vector<int>  {i, 26}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"27",  std::vector<int>  {i, 27}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"28",  std::vector<int>  {i, 28}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"29",  std::vector<int>  {i, 29}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"30",  std::vector<int>  {i, 30}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"31",  std::vector<int>  {i, 31}));
      map_btw_MIDCH_and_Name.insert(std::make_pair( std::to_string(i)+"32",  std::vector<int>  {i, 32}));
    }
    return map_btw_MIDCH_and_Name;
}

#endif // FUNCTION_H
