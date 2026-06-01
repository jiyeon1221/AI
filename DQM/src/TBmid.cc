#include "TBmid.h"

#include "stdio.h"
#include <numeric>

TBwaveform::TBwaveform()
    : channel_(-1), waveform_(0) {}

void TBwaveform::init()
{
  waveform_.resize(1024, 0);
}

std::vector<float> TBwaveform::pedcorrectedWaveform(float ped) const
{
  std::vector<float> result;
  result.reserve(waveform_.size());

  for (unsigned idx = 0; idx < waveform_.size(); idx++)
  {
    float abin = static_cast<float>(ped) - static_cast<float>(waveform_.at(idx));
    result.emplace_back(abin);
  }

  return std::move(result);
}

std::vector<float> TBwaveform::pedcorrectedWaveform() const
{
  return pedcorrectedWaveform(100);
}

std::vector<float> TBwaveform::pedcorrectedWaveform(int pedBins) const
{
  std::vector<float> result;
  result.reserve(waveform_.size());

  // Pedestal averaged over the first `pedBins` waveform bins (skipping bin
  // 0). Caller picks the window so the value can come from TBpedConfig and
  // stay consistent with TBplotengine / TBaux Get{Int,Peak}ADC.
  if (pedBins <= 0 || static_cast<size_t>(pedBins) >= waveform_.size())
    pedBins = 100;

  float ped = 0;
  const float denom = static_cast<float>(pedBins);
  for (int i = 1; i <= pedBins; i++)
    ped += static_cast<float>(waveform_.at(i)) / denom;

  for (unsigned idx = 0; idx < waveform_.size(); idx++)
  {
    float abin = ped - static_cast<float>(waveform_.at(idx));
    result.emplace_back(abin);
  }

  return std::move(result);
}

float TBwaveform::pedcorrectedADC(float ped, int buffer) const
{
  auto corrected = pedcorrectedWaveform(ped);

  return std::accumulate(corrected.rbegin() + buffer, corrected.rend(), 0.);
}

float TBwaveform::emulfastADC(int rise, int width, int buffer) const
{
  auto waveform_eff = waveform_;

  for (int i = 0; i < buffer; ++i) // remove last 24 bins
    waveform_eff.pop_back();

  waveform_eff.erase(waveform_eff.begin()); // remove 0th bin

  auto result = std::min_element(waveform_eff.begin(), waveform_eff.end());

  int idx_min = result - waveform_eff.begin();

  auto waveform_shfted = waveform_eff;

  std::rotate(waveform_shfted.begin(), waveform_shfted.begin() + idx_min, waveform_shfted.end());
  std::rotate(waveform_shfted.rbegin(), waveform_shfted.rbegin() + (rise + width), waveform_shfted.rend());

  float adc_sig = 0.0;
  float adc_ped = 0.0;

  for (int i = 0; i < width; ++i)
  {
    adc_ped += 4096.0 - waveform_shfted.at(i);
    adc_sig += 4096.0 - waveform_shfted.at(i + width);
  }

  return adc_sig - adc_ped;
}

TBfastmode::TBfastmode()
    : channel_(-1), adc_(0), timing_(0) {}

TBmidbase::TBmidbase()
    : evt_(0), run_(0), mid_(0),
      tcb_trig_type_(0),
      tcb_trig_number_(0),
      tcb_trig_time_(0),
      local_trig_number_(0),
      local_trigger_pattern_(0),
      local_trig_time_(0),
      channelsize_(0) {}

TBmidbase::TBmidbase(int ev, int ru, int mi)
    : evt_(ev), run_(ru), mid_(mi),
      tcb_trig_type_(0),
      tcb_trig_number_(0),
      tcb_trig_time_(0),
      local_trig_number_(0),
      local_trigger_pattern_(0),
      local_trig_time_(0),
      channelsize_(0) {}

void TBmidbase::setTCB(int ty, int nu, long long ti)
{
  tcb_trig_type_ = ty;
  tcb_trig_number_ = nu;
  tcb_trig_time_ = ti;
}

void TBmidbase::setLocal(int nu, int pa, long long ti)
{
  local_trig_number_ = nu;
  local_trigger_pattern_ = pa;
  local_trig_time_ = ti;
}

void TBmidbase::print()
{
  long long diff_time = local_trig_time_ - tcb_trig_time_;
  printf("evt = %d, run # = %d, mid = %d\n", tcb_trig_number_, run_, mid_);
  printf("trigger type = %X, local trigger pattern = %X\n", tcb_trig_type_, local_trigger_pattern_);
  printf("TCB trigger # = %d, local trigger # = %d\n", tcb_trig_number_, local_trig_number_);
  printf("TCB trigger time = %lld, local trigger time = %lld, difference = %lld\n", tcb_trig_time_, local_trig_time_, diff_time);
  printf("-----------------------------------------------------------------------\n");
}

template <typename T>
TBmid<T>::TBmid(int ev, int ru, int mi)
    : TBmidbase(ev, ru, mi), channels_(0) {}

template <typename T>
TBmid<T>::TBmid()
    : TBmidbase(), channels_(0) {}

template <typename T>
TBmid<T>::TBmid(const TBmidbase &base)
    : TBmidbase(base), channels_(0) {}

template <typename T>
void TBmid<T>::setChannels(std::vector<T> ch)
{
  channels_ = ch;
  channelsize_ = static_cast<int>(channels_.size());
}

template class TBmid<TBwaveform>;
template class TBmid<TBfastmode>;
