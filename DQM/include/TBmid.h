#ifndef TBmid_h
#define TBmid_h 1

#include <vector>
#include <algorithm>
#include <iterator>

class TBwaveform
{
public:
  TBwaveform();
  ~TBwaveform() {}

  void init();

  void setChannel(int ch) { channel_ = ch; }
  int channel() const { return channel_; }

  std::vector<short> waveform() const { return waveform_; }

  std::vector<float> pedcorrectedWaveform(float ped) const;
  std::vector<float> pedcorrectedWaveform() const;            // 100-bin default
  std::vector<float> pedcorrectedWaveform(int pedBins) const; // configurable
  float pedcorrectedADC(float ped, int buffer = 24) const;
  float emulfastADC(int rise, int width, int buffer = 24) const;

  void fill(unsigned int bin, short val) { waveform_.at(bin) = val; }

private:
  int channel_;
  std::vector<short> waveform_;
};

class TBfastmode
{
public:
  TBfastmode();
  ~TBfastmode() {}

  int adc() const { return adc_; }
  int timing() const { return timing_; }
  void setAdc(int ad) { adc_ = ad; }
  void setTiming(int ti) { timing_ = ti; }

  void setChannel(int ch) { channel_ = ch; }
  int channel() const { return channel_; }

private:
  int channel_;
  int adc_;
  int timing_;
};

class TBmidbase
{
public:
  TBmidbase();
  TBmidbase(int ev, int ru, int mi);
  ~TBmidbase() {}

  int evt() const { return evt_; }
  int run() const { return run_; }
  int mid() const { return mid_; }

  int tcb_trig_type() const { return tcb_trig_type_; }
  int tcb_trig_number() const { return tcb_trig_number_; }
  long long tcb_trig_time() const { return tcb_trig_time_; }
  void setTCB(int ty, int nu, long long ti);

  int local_trig_number() const { return local_trig_number_; }
  int local_trigger_pattern() const { return local_trigger_pattern_; }
  long long local_trig_time() const { return local_trig_time_; }
  void setLocal(int nu, int pa, long long ti);

  int channelsize() const { return channelsize_; }

  void print();

protected:
  int channelsize_;

private:
  // metadata
  int evt_;
  int run_;
  int mid_;
  int tcb_trig_type_;
  int tcb_trig_number_;
  long long tcb_trig_time_;
  int local_trig_number_;
  int local_trigger_pattern_;
  long long local_trig_time_;
};

template <class T> // waveform or fastmode
class TBmid : public TBmidbase
{
public:
  TBmid();
  TBmid(const TBmidbase &base);
  TBmid(int ev, int ru, int mi);
  ~TBmid() {}

  const T channel(unsigned int idx) const { return channels_.at(idx); }
  void setChannels(std::vector<T> ch);

private:
  std::vector<T> channels_;
};

#endif
