/**
 * @file function.h
 * @brief Utility functions for DAQ waveform analysis and DWC position calculation
 * 
 * This file contains essential functions for processing test beam data:
 * - Waveform analysis (pedestal, peak finding, integration)
 * - DWC position reconstruction
 * - Event selection utilities
 * - Progress reporting
 * 
 * @note Waveform structure:
 *   - 1000 time bins (200 ps/bin = 200 ns total window)
 *   - 4096 ADC bins (12-bit digitization)
 *   - Baseline pedestal ~3500 ADC
 *   - Negative signal polarity (signals go downward)
 */

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

/**
 * @brief Standard color palette for ROOT histograms
 * 
 * Provides a consistent set of distinguishable colors for multi-channel
 * histogram plotting. Colors are ordered for maximum visual separation.
 * 
 * @note Colors correspond to ROOT's predefined color constants:
 *   1=kBlack, 2=kRed, 4=kBlue, 417=kGreen+1, 616=kMagenta, etc.
 */
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

/**
 * @brief Calculate pedestal (baseline) from beginning of waveform
 * 
 * Computes the average ADC value from bins 1-100 to determine the baseline
 * level before any signal arrives. This is the standard pedestal calculation.
 * 
 * @param waveform Raw ADC waveform data (typically 1000 bins)
 * @return Average ADC value in the pedestal region (typically ~3500 ADC)
 * 
 * @note Skips bin 0 to avoid potential trigger artifacts
 * @note Uses first 100 bins assuming signal comes later in waveform
 */
float getPed(std::vector<short> waveform) {
  return std::accumulate( waveform.begin() + 1, waveform.begin() + 101, 0.) / 100.;
}

/**
 * @brief Calculate pedestal from end of waveform (alternative method)
 * 
 * Computes baseline from the last 100 bins of the waveform. Useful when
 * signals might occur early in the waveform or for cross-checking.
 * 
 * @param waveform Raw ADC waveform data
 * @return Average ADC value from the tail region
 * 
 * @note Uses bins [size-124, size-24] to avoid potential end effects
 */
float getPedfromBack(std::vector<short> waveform) {
  return std::accumulate( waveform.end() - 124, waveform.end() - 24, 0.) / 100.;
}

//////////////////////////////////////////////////////////////////////////////
// MINIMUM FINDING FUNCTIONS (PEAK DETECTION)
//////////////////////////////////////////////////////////////////////////////

/**
 * @brief Find minimum ADC value in waveform (raw peak detection)
 * 
 * Locates the lowest ADC value in the waveform, which corresponds to the
 * signal peak due to negative polarity (signals go downward from baseline).
 * 
 * @param waveform Raw ADC waveform data
 * @return Minimum ADC value found (lowest point = signal peak)
 * 
 * @note Excludes first and last 23 bins to avoid edge effects
 * @note For calibrated peak amplitude, use GetPeak() instead
 */
float getMin(std::vector<short> waveform) {
  return *(std::min_element(waveform.begin() + 1, waveform.end() - 23));
}

/**
 * @brief Find minimum ADC value within specified range
 * 
 * Searches for the lowest ADC value only within the given time window.
 * Useful for targeted peak finding when signal timing is known.
 * 
 * @param waveform Raw ADC waveform data
 * @param from Starting bin index (inclusive)
 * @param end Ending bin index (exclusive)
 * @return Minimum ADC value in the specified range
 */
float getMinFrom(std::vector<short> waveform, int from, int end) {
  int minus = waveform.size() - end;
  return *(std::min_element(waveform.begin() + from, waveform.end() - minus));
}

/**
 * @brief Get bin index of minimum ADC value (peak position)
 * 
 * Returns the time bin where the signal peak occurs. Essential for
 * timing analysis and leading edge calculations.
 * 
 * @param waveform Raw ADC waveform data
 * @return Bin index of the minimum value (peak timing)
 * 
 * @note Convert to time using: time_ns = bin_index * 0.2 (for 200ps/bin)
 */
int getMinIdx(std::vector<short> waveform) {
  return std::distance( waveform.begin(), std::min_element(waveform.begin() + 1, waveform.end() - 23) );
}

/**
 * @brief Get bin index of minimum value within specified range
 * 
 * @param waveform Raw ADC waveform data
 * @param from Starting bin index (inclusive)
 * @param end Ending bin index (exclusive)
 * @return Bin index of minimum value in the specified range
 */
int getMinIdxFrom(std::vector<short> waveform, int from, int end) {
  int minus = waveform.size() - end;
  return std::distance( waveform.begin(), std::min_element(waveform.begin() + from, waveform.end() - minus) );
}

//////////////////////////////////////////////////////////////////////////////
// INTERPOLATION AND TIMING FUNCTIONS
//////////////////////////////////////////////////////////////////////////////

/**
 * @brief Perform linear interpolation between two points
 * 
 * Generic linear interpolation utility for finding precise crossing points
 * between discrete measurement points.
 * 
 * @param x1 X-coordinate of first point
 * @param y1 Y-coordinate of first point  
 * @param x2 X-coordinate of second point
 * @param y2 Y-coordinate of second point
 * @param threshold Y-value to find corresponding X-coordinate
 * @return Interpolated X-coordinate where line crosses threshold
 */
double linearInterpolation(double x1, double y1, double x2, double y2, double threshold) {
    return x1 + (threshold - y1) * (x2 - x1) / (y2 - y1);
}

/**
 * @brief Interpolate precise threshold crossing bin for timing analysis
 * 
 * Given a bin where threshold crossing occurred, interpolates the exact
 * fractional bin position using linear interpolation between adjacent points.
 * 
 * @param waveform Raw ADC waveform data
 * @param thrs_bin Bin index where threshold crossing occurred
 * @param thrs Threshold value in pedestal-corrected ADC units
 * @return Precise fractional bin position of threshold crossing
 * 
 * @note Returns interpolated bin number, convert to time as needed
 * @note Uses pedestal correction: signal = pedestal - raw_ADC
 */
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

/**
 * @brief Scale waveform for average time structure calculation
 * 
 * Normalizes each bin by the total number of events to create an average
 * waveform. Used in avgTimeStruc analysis to show typical signal shape.
 * 
 * @param waveform Raw ADC waveform from single event
 * @param maxEntry Total number of events being averaged
 * @return Scaled waveform with each bin divided by event count
 * 
 * @note Result represents fractional contribution to average waveform
 */
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

/**
 * @brief Calculate integrated ADC with automatic pedestal correction
 * 
 * Computes the total charge collected in a waveform by integrating the
 * pedestal-corrected signal over a specified time window. This is the
 * primary method for measuring signal strength.
 * 
 * @param waveform Raw ADC waveform data
 * @param startBin Starting bin for integration (inclusive)
 * @param endBin Ending bin for integration (exclusive)
 * @return Integrated ADC value (charge proportional to energy)
 * 
 * @note Automatically calculates pedestal from bins 1-100
 * @note Signal polarity correction: integrates (pedestal - raw_ADC)
 * @note Typical integration windows: 100-500 bins for most detectors
 */
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

/**
 * @brief Find peak amplitude with automatic pedestal correction
 * 
 * Locates the maximum signal amplitude (peak height) within a specified
 * time window. Essential for amplitude-based analysis and peak ADC distributions.
 * 
 * @param waveform Raw ADC waveform data
 * @param startBin Starting bin for peak search (inclusive)
 * @param endBin Ending bin for peak search (exclusive)
 * @return Peak amplitude in pedestal-corrected ADC units
 * 
 * @note Automatically calculates pedestal from bins 1-100
 * @note Returns maximum of (pedestal - raw_ADC) in the search window
 * @note Typical search windows: 200-600 bins for most detectors
 */
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

/**
 * @brief Calculate integrated ADC using provided pedestal value
 * 
 * Same as GetInt() but uses externally calculated pedestal instead of
 * computing it from the waveform. Useful for consistent pedestal across events.
 * 
 * @param waveform Raw ADC waveform data
 * @param startBin Starting bin for integration (inclusive)
 * @param endBin Ending bin for integration (exclusive)
 * @param ped Pedestal value to use for correction
 * @return Integrated ADC value using provided pedestal
 */
double GetIntWithPed(std::vector<short> waveform, int startBin, int endBin, double ped)
{  
  std::vector<double> pedCorrectedWave;
  for (int i = 0; i < waveform.size(); i++)
    pedCorrectedWave.push_back(ped - (double)waveform.at(i));

  return (std::accumulate(pedCorrectedWave.begin() + startBin, pedCorrectedWave.begin() + endBin, 0.));
}

/**
 * @brief Find peak amplitude using provided pedestal value
 * 
 * Same as GetPeak() but uses externally calculated pedestal instead of
 * computing it from the waveform.
 * 
 * @param waveform Raw ADC waveform data
 * @param startBin Starting bin for peak search (inclusive)
 * @param endBin Ending bin for peak search (exclusive)
 * @param ped Pedestal value to use for correction
 * @return Peak amplitude using provided pedestal
 */
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

/**
 * @brief Convert waveform bin index to time in nanoseconds
 * 
 * Converts discrete time bin numbers to actual time values based on the
 * DAQ sampling rate. Used for DWC timing analysis and position reconstruction.
 * 
 * @param bin Waveform bin index (0-999 for typical 1000-bin waveforms)
 * @return Time in nanoseconds corresponding to the bin
 * 
 * @note Current calibration: 200ns total window / 1000 bins = 0.2 ns/bin
 * @note This differs from the nominal 0.2 ns/bin - may need verification
 */
double getTime(double bin, double time_window=200.) {
  return time_window * (bin / 1000.);
}

/**
 * @brief Get bin index of signal peak (minimum ADC value)
 * 
 * Finds the time bin where the signal peak occurs. For DWC chambers,
 * peak timing is used to calculate particle position via time-of-flight.
 * 
 * @param waveform Raw ADC waveform data from DWC channel
 * @return Bin index of the signal peak (minimum value)
 * 
 * @note Excludes edge bins to avoid artifacts
 * @note Peak timing accuracy is crucial for position resolution
 */
int getPeakBin(std::vector<short> waveform) {
    return ( std::min_element(waveform.begin()+1, waveform.end()-23) - waveform.begin() );
}

/**
 * @brief Find leading edge bin at specified threshold fraction
 * 
 * Locates the time bin where the signal first crosses a threshold defined
 * as a fraction of the peak amplitude. Used for precise timing measurements.
 * 
 * @param waveform Raw ADC waveform data
 * @param threshold Fraction of peak amplitude (0.0-1.0, typically 0.1-0.5)
 * @param start Starting bin for search window
 * @param end Ending bin for search window
 * @return Bin index where signal crosses threshold, or -1 if not found
 * 
 * @note Threshold is relative to peak: thr_value = peak_amplitude * threshold
 * @note Leading edge timing provides better precision than peak timing
 */
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

/**
 * @brief Calculate leading edge time with interpolation (800ns window)
 * 
 * Finds the precise time when signal crosses the threshold using linear
 * interpolation between adjacent bins for sub-bin precision.
 * 
 * @param waveform Raw ADC waveform data
 * @param threshold Fraction of peak amplitude for leading edge
 * @param start Starting bin for search window
 * @param end Ending bin for search window
 * @return Leading edge time in nanoseconds with interpolation
 * 
 * @note Uses 800ns time calibration (0.8 ns/bin)
 * @note Interpolation provides timing resolution better than bin width
 */
float getLeadingEdgeTime_interpolated800(std::vector<short> waveform, float threshold, int start, int end) {
    
    int leadingEdgeBin = getLeadingEdgeBin(waveform, threshold, start, end);

    float thr = GetPeak(waveform, start, end) * threshold;

    if (leadingEdgeBin == 1)
      return getTime(leadingEdgeBin, 800.);

    float interpolated_bin = interpolate(waveform, leadingEdgeBin, thr);

    return getTime(interpolated_bin, 800.);
}

/**
 * @brief Calculate leading edge time with interpolation (200ns window)
 * 
 * Same as getLeadingEdgeTime() but uses 200ns time calibration instead
 * of 800ns. Used for specific detector configurations.
 * 
 * @param waveform Raw ADC waveform data
 * @param threshold Fraction of peak amplitude for leading edge
 * @param start Starting bin for search window
 * @param end Ending bin for search window
 * @return Leading edge time in nanoseconds (200ns calibration)
 * 
 * @note Uses 200ns time calibration (0.2 ns/bin)
 */
float getLeadingEdgeTime_interpolated200(std::vector<short> waveform, float threshold, int start, int end) {
    
    int leadingEdgeBin = getLeadingEdgeBin(waveform, threshold, start, end);

    float thr = GetPeak(waveform, start, end) * threshold;

    if (leadingEdgeBin == 1)
      return getTime(leadingEdgeBin, 200.);

    float interpolated_bin = interpolate(waveform, leadingEdgeBin, thr);

    return getTime(interpolated_bin, 200.);
}

/**
 * @brief Calculate leading edge time without interpolation
 * 
 * Simpler version that returns the time of the bin where threshold
 * crossing occurs, without sub-bin interpolation.
 * 
 * @param waveform Raw ADC waveform data
 * @param threshold Fraction of peak amplitude for leading edge
 * @param start Starting bin for search window
 * @param end Ending bin for search window
 * @return Leading edge time in nanoseconds (bin precision only)
 */
float getLeadingEdgeTime_noInterpolation(std::vector<short> waveform, float threshold, int start, int end) {
  int bin = getLeadingEdgeBin(waveform, threshold, start, end);
  return getTime(bin, 800.);
}

/**
 * @brief Get peak timing from waveform
 * 
 * Returns the time when the signal reaches its peak amplitude.
 * Less precise than leading edge timing but simpler to calculate.
 * 
 * @param waveform Raw ADC waveform data
 * @return Peak time in nanoseconds
 */
float getPeakTime(std::vector<short> waveform) {
    int peakBin = getPeakBin(waveform);
    return (getTime(peakBin, 800.));
}

//////////////////////////////////////////////////////////////////////////////
// DWC POSITION RECONSTRUCTION FUNCTIONS
//////////////////////////////////////////////////////////////////////////////

// Calculate DWC position using DWC waveform peak timing (timing == nanosecond)
// DWC X-axis position : { (Waveform peak timing from DWC Right ch) - (Waveform peak timing from DWC Left ch) } * (calibrated DWC x-axis slope value) + (calibrated DWC x-axis intercept value)
// DWC Y-axis position : { (Waveform peak timing from DWC Up ch) - (Waveform peak timing from DWC Down ch) } * (calibrated DWC y-axis slope value) + (calibrated DWC y-axis intercept value)
// Subtract x and y offset from calculated DWC x-axis and y-axis position to make mean value of DWC position plot aligns to center. That is, (0 mm, 0 mm) position.
// x and y offset can be obtained from non-corrected DWC position plot's mean value.

/**
 * @brief Calculate DWC1 position from timing measurements
 * 
 * Reconstructs the (X,Y) position where a particle crossed DWC1 using
 * the time-of-flight differences between opposing wire pairs.
 * 
 * Physics principle: A particle hitting closer to one wire will reach 
 * that wire faster, creating a timing difference proportional to position.
 * 
 * @param dwc1Time Vector of 4 timing values [Right, Left, Up, Down] in nanoseconds
 * @param dwc1Offset Vector of 2 offset corrections [X_offset, Y_offset] in mm
 * @return Vector containing [X_position, Y_position] in mm
 * 
 * @note Calibration constants from TB2024 (2800V, 40% leading edge threshold)
 * @note X = (t_right - t_left) * slope + offset - x_correction
 * @note Y = (t_up - t_down) * slope + offset - y_correction
 * @note Slope units: mm/ns, determined from calibration runs
 */
std::vector<float> getDWC1position(std::vector<float> dwc1Time, std::vector<float> dwc1Offset) {
    // // TB2024 calibration constants (2800V, leading edge 40%)
    // float dwc1_horizontal_Slope  = 0.1830;   // mm/ns for X position
    // float dwc1_horizontal_Offset = -0.04539; // mm baseline offset
    // float dwc1_Vertical_Slope    = -0.1798;  // mm/ns for Y position (negative due to coordinate system)
    // float dwc1_Vertical_Offset   = 0.06994;  // mm baseline offset

    // TB2025 result (2800V, leading edge 40%)
    float dwc1_horizontal_Slope  = 0.180654; // This is calib. const. for upstream -> downstream view
    float dwc1_horizontal_Offset = 0.217961; // This is calib. const. for upstream -> downstream view
    float dwc1_Vertical_Slope    = -0.180342;    // This is calib. const. for upstream -> downstream view
    float dwc1_Vertical_Offset   = -0.0994697;  // This is calib. const. for upstream -> downstream view
    // float dwc1_horizontal_Slope_downstream = -0.180654;
    // float dwc1_horizontal_Offset_downstream = -0.217961;

    std::vector<float> dwc1Position;

    // Position calculation: time difference * calibration + offset - correction
    // dwc1Time order: {Right, Left, Up, Down}
    float horizontalPos = ((float)(dwc1Time.at(0) - dwc1Time.at(1)) * dwc1_horizontal_Slope) 
                         + dwc1_horizontal_Offset - dwc1Offset.at(0);
    float verticalPos = ((float)(dwc1Time.at(2) - dwc1Time.at(3)) * dwc1_Vertical_Slope) 
                       + dwc1_Vertical_Offset - dwc1Offset.at(1);

    dwc1Position.push_back(horizontalPos);
    dwc1Position.push_back(verticalPos);

    // Return DWC 1 (X, Y) position in mm
    return dwc1Position;
}

/**
 * @brief Calculate DWC2 position from timing measurements
 * 
 * Same principle as getDWC1position() but with DWC2-specific calibration
 * constants. DWC2 is positioned downstream from DWC1.
 * 
 * @param dwc2Time Vector of 4 timing values [Right, Left, Up, Down] in nanoseconds
 * @param dwc2Offset Vector of 2 offset corrections [X_offset, Y_offset] in mm
 * @return Vector containing [X_position, Y_position] in mm
 * 
 * @note Calibration constants from TB2024 (2800V, 40% leading edge threshold)
 * @note Each DWC has unique calibration due to geometry and electronics differences
 */
std::vector<float> getDWC2position(std::vector<float> dwc2Time, std::vector<float> dwc2Offset) {
    // // TB2024 calibration constants (2800V, leading edge 40%)
    // float dwc2_horizontal_Slope  = 0.1818;   // mm/ns for X position
    // float dwc2_horizontal_Offset = 0.02975;  // mm baseline offset
    // float dwc2_Vertical_Slope    = -0.1818;  // mm/ns for Y position
    // float dwc2_Vertical_Offset   = 0.02572;  // mm baseline offset

    // // TB2025 result (2800V, leading edge 40%)
    float dwc2_horizontal_Slope  = 0.181416; // This is calib. const. for upstream -> downstream view
    float dwc2_horizontal_Offset = -0.00911072; // This is calib. const. for upstream -> downstream view
    float dwc2_Vertical_Slope    = -0.17822;    // This is calib. const. for upstream -> downstream view
    float dwc2_Vertical_Offset   = -0.0489771;  // This is calib. const. for upstream -> downstream view
    // float dwc2_horizontal_Slope_downstream = -0.181416;
    // float dwc2_horizontal_Offset_downstream = 0.00911072;

    std::vector<float> dwc2Position;

    float horizontalPos = ((float)(dwc2Time.at(0) - dwc2Time.at(1)) * dwc2_horizontal_Slope) 
                         + dwc2_horizontal_Offset - dwc2Offset.at(0);
    float verticalPos = ((float)(dwc2Time.at(2) - dwc2Time.at(3)) * dwc2_Vertical_Slope) 
                       + dwc2_Vertical_Offset - dwc2Offset.at(1);

    dwc2Position.push_back(horizontalPos);
    dwc2Position.push_back(verticalPos);

    return dwc2Position;
}

//////////////////////////////////////////////////////////////////////////////
// CLOCK-BASED DWC POSITION FUNCTIONS (Alternative timing method)
//////////////////////////////////////////////////////////////////////////////

/**
 * @brief Calculate DWC1 position using clock values instead of waveform timing
 * 
 * Alternative position calculation using fast digitizer clock values rather
 * than waveform peak timing. Used for fast mode data acquisition.
 * 
 * @param dwc1Time Vector of 4 clock values [Right, Left, Up, Down] in clock units
 * @return Vector containing [X_position, Y_position] in mm
 * 
 * @note Clock to time conversion: time_ns = clock_value * 25.0 / 1000.0
 * @note Uses different calibration constants optimized for clock timing
 * @note Includes sign flips due to coordinate system conventions
 */
std::vector<float> getDWC1positionUsingClock(std::vector<float> dwc1Time) {
    // // TB2024 calibration constants (2800V, leading edge 40%)
    // float dwc1_horizontal_Slope  = 0.1830;   // mm/ns for X position
    // float dwc1_horizontal_Offset = -0.04539; // mm baseline offset
    // float dwc1_Vertical_Slope    = -0.1798;  // mm/ns for Y position (negative due to coordinate system)
    // float dwc1_Vertical_Offset   = 0.06994;  // mm baseline offset

    // TB2025 result (2800V, leading edge 40%)
    float dwc1_horizontal_Slope  = 0.180654; // This is calib. const. for upstream -> downstream view
    float dwc1_horizontal_Offset = 0.217961; // This is calib. const. for upstream -> downstream view
    float dwc1_Vertical_Slope    = -0.180342;    // This is calib. const. for upstream -> downstream view
    float dwc1_Vertical_Offset   = -0.0994697;  // This is calib. const. for upstream -> downstream view
    // float dwc1_horizontal_Slope_downstream = -0.180654;
    // float dwc1_horizontal_Offset_downstream = -0.217961;

    std::vector<float> dwc1Position;

    // Convert clock to ns, then apply calibration with coordinate corrections
    float horizontalPos = -( ( (float)(dwc1Time.at(0) - dwc1Time.at(1)) * 25. / 1000. * dwc1_horizontal_Slope ) + dwc1_horizontal_Offset );
    float verticalPos = ( (float)(dwc1Time.at(2) - dwc1Time.at(3)) * 25. / 1000. * dwc1_Vertical_Slope ) + dwc1_Vertical_Offset;

    dwc1Position.push_back(horizontalPos);
    dwc1Position.push_back(verticalPos);

    return dwc1Position;
}

/**
 * @brief Calculate DWC2 position using clock values
 * 
 * Clock-based version of DWC2 position calculation with DWC2-specific
 * calibration constants.
 * 
 * @param dwc2Time Vector of 4 clock values [Right, Left, Up, Down] in clock units
 * @return Vector containing [X_position, Y_position] in mm
 */
std::vector<float> getDWC2positionUsingClock(std::vector<float> dwc2Time) {
    // // TB2024 calibration constants (2800V, leading edge 40%)
    // float dwc2_horizontal_Slope  = 0.1818;   // mm/ns for X position
    // float dwc2_horizontal_Offset = 0.02975;  // mm baseline offset
    // float dwc2_Vertical_Slope    = -0.1818;  // mm/ns for Y position
    // float dwc2_Vertical_Offset   = 0.02572;  // mm baseline offset

    // // TB2025 result (2800V, leading edge 40%)
    float dwc2_horizontal_Slope  = 0.181416; // This is calib. const. for upstream -> downstream view
    float dwc2_horizontal_Offset = -0.00911072; // This is calib. const. for upstream -> downstream view
    float dwc2_Vertical_Slope    = -0.17822;    // This is calib. const. for upstream -> downstream view
    float dwc2_Vertical_Offset   = -0.0489771;  // This is calib. const. for upstream -> downstream view
    // float dwc2_horizontal_Slope_downstream = -0.181416;
    // float dwc2_horizontal_Offset_downstream = 0.00911072;

    std::vector<float> dwc2Position;

    float horizontalPos = -( ( (float)(dwc2Time.at(0) - dwc2Time.at(1)) * 25. / 1000. * dwc2_horizontal_Slope ) + dwc2_horizontal_Offset );
    float verticalPos = ( (float)(dwc2Time.at(2) - dwc2Time.at(3)) * 25. / 1000. * dwc2_Vertical_Slope ) + dwc2_Vertical_Offset;

    dwc2Position.push_back(horizontalPos);
    dwc2Position.push_back(verticalPos);

    return dwc2Position;
}

/**
 * @brief Extract position offset corrections from DWC histogram
 * 
 * Calculates the mean X and Y positions from a 2D DWC position histogram
 * to determine offset corrections needed to center the beam at (0,0).
 * 
 * @param dwcHist 2D histogram of uncorrected DWC positions
 * @return Vector containing [X_offset, Y_offset] in mm
 * 
 * @note Used to calculate the dwcOffset parameters for position functions
 * @note Run this on a preliminary analysis to get centering corrections
 */
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

/**
 * @brief Apply DWC correlation cut for particle tracking
 * 
 * Checks if a particle trajectory is consistent between DWC1 and DWC2 by
 * ensuring the position difference is within acceptable limits. Used to
 * reject scattered or multi-particle events.
 * 
 * @param dwc1_correctedPosition [X, Y] position at DWC1 in mm
 * @param dwc2_correctedPosition [X, Y] position at DWC2 in mm  
 * @param threshold Maximum allowed position difference in mm (default: 1.5mm)
 * @return true if particle trajectory is consistent, false otherwise
 * 
 * @note Assumes straight-line particle trajectory between DWCs
 * @note Threshold of 1.5mm allows for detector resolution and beam divergence
 * @note Essential for clean event selection in calorimeter analysis
 */
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

/**
 * @brief Display progress bar for long-running analysis
 * 
 * Shows a visual progress indicator with percentage completion during
 * event processing. Improves user experience for large datasets.
 * 
 * @param currentStep Current event or step number being processed
 * @param totalStep Total number of events or steps to process
 * 
 * @note Uses carriage return (\r) to update same line
 * @note Call every N events (e.g., every 1000) to avoid output flooding
 * @note Progress bar width is fixed at 70 characters
 * 
 * @example
 * for(int i = 0; i < maxEvents; i++) {
 *     if(i % 1000 == 0) printProgress(i, maxEvents);
 *     // ... process event ...
 * }
 */
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

/**
 * @brief Create mapping between MID-Channel strings and module-channel pairs
 * 
 * Generates a comprehensive lookup table that maps MID-Channel identifier
 * strings (e.g., "101", "102", "1503") to their corresponding [MID, Channel]
 * number pairs. Essential for DAQ channel identification and data routing.
 * 
 * @return Map with MID-CH string keys and [MID, Channel] vector values
 * 
 * @note Covers MIDs 1-20, each with channels 01-32 (32 channels per MID)
 * @note String format: MID concatenated with zero-padded 2-digit channel
 * @note Total entries: 20 MIDs × 32 channels = 640 mappings
 * 
 * @example Map entries:
 *   "101" → [1, 1]   (MID 1, Channel 1)
 *   "102" → [1, 2]   (MID 1, Channel 2)
 *   "201" → [2, 1]   (MID 2, Channel 1)
 *   "2032" → [20, 32] (MID 20, Channel 32)
 * 
 * @note Used by TButility for channel identification in data processing
 */
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