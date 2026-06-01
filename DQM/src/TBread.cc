#include "TBread.h"
#include "TBmid.h"
#include "TBevt.h"
#include "TButility.h"

#include <stdexcept>
#include <chrono>
#include <format>

#include "TSystem.h"
#include "TFile.h"
#include "TTree.h"

template <typename T>
FileController<T>::FileController(int fRunNum_, bool fIsLive_, int fMID_, std::string fBaseDir_, int fMaxFileNum_)
    : fMode(), fRawData(0), fRunNum(fRunNum_), fIsLive(fIsLive_), fMID(fMID_), fBaseDir(fBaseDir_), fNextFileNum(0), fMaxFileNum(fMaxFileNum_), fTotalEventNum(0), fCurrentEventNum(0), fTotalMaxEventNum(0), fCurrentMaxEventNum(0)
{
  ANSI = ANSI_CODE();

  if (!fIsLive)
    init();
}

template <typename T>
void FileController<T>::init()
{

  if (fMaxFileNum == -1)
    fMaxFileNum = 999;

  for (int i = 0; i < fMaxFileNum; i++)
  {
    std::string aFileName = GetFileName(fMode, i);
    if (!access(aFileName.c_str(), F_OK))
    {
      int maxEvent = GetMaximum(fMode, aFileName);
      fTotalMaxEventNum += maxEvent;
      std::cout << "file scanning : " << aFileName << " - Max Event : " << maxEvent << " / " << fTotalMaxEventNum << std::endl;
    }
    else
    {
      break;
    }
  }
  std::cout << " " << std::endl;

  OpenFile();
}

template <typename T>
std::string FileController<T>::GetFileName()
{
  return GetFileName(fMode, fNextFileNum);
}

template <typename T>
std::string FileController<T>::GetFileName(TBwaveform fMode_, int aFileNum)
{
  return fBaseDir + "/Run_" + std::to_string(fRunNum) + "/Run_" + std::to_string(fRunNum) + "_Wave/Run_" + std::to_string(fRunNum) + "_Wave_MID_" + std::to_string(fMID) + "/Run_" + std::to_string(fRunNum) + "_Wave_MID_" + std::to_string(fMID) + "_FILE_" + std::to_string(aFileNum) + ".dat";
}

template <typename T>
std::string FileController<T>::GetFileName(TBfastmode fMode_, int aFileNum)
{
  return fBaseDir + "/Run_" + std::to_string(fRunNum) + "/Run_" + std::to_string(fRunNum) + "_Fast/Run_" + std::to_string(fRunNum) + "_Fast_MID_" + std::to_string(fMID) + "/Run_" + std::to_string(fRunNum) + "_Fast_MID_" + std::to_string(fMID) + "_FILE_" + std::to_string(aFileNum) + ".dat";
}

template <typename T>
void FileController<T>::OpenFile()
{

  fFileName = GetFileName();

  if (access(fFileName.c_str(), F_OK))
    throw std::runtime_error(ANSI.RED + ANSI.BOLD + "FileController<T>::OpenFile - Does not exist : " + fFileName + ANSI.END);

  fCurrentMaxEventNum = GetMaximum();
  fCurrentEventNum = 0;

  fRawData = fopen(fFileName.c_str(), "rb");

  if (fRawData == NULL)
    throw std::runtime_error(ANSI.RED + ANSI.BOLD + "FileController<T>::OpenFile - File might be damaged? : " + fFileName + ANSI.END);

  fNextFileNum++;

  if (fIsLive) {
    std::cout << ANSI.BOLD + "File scanning : " + ANSI.END << ANSI.GREEN + ANSI.BOLD + fFileName + ANSI.END << " - Current : " << fCurrentEventNum << " / " << fTotalEventNum << " - Max Event : " << fCurrentMaxEventNum << " / " << fTotalMaxEventNum << std::endl;
    std::cout << " " << std::endl;
  }
}

template <typename T>
TBmid<T> FileController<T>::ReadEvent()
{

  return std::move(ReadEvent(fMode));
}

template <typename T>
TBmid<TBwaveform> FileController<T>::ReadEvent(TBwaveform fMode_)
{

  CheckOverflow();
  fTotalEventNum++;
  fCurrentEventNum++;

  return std::move(ReadWaveformMid());
}

template <typename T>
TBmid<TBfastmode> FileController<T>::ReadEvent(TBfastmode fMode_)
{

  CheckOverflow();
  fTotalEventNum++;
  fCurrentEventNum++;

  return std::move(ReadFastmodeMid());
}

template <typename T>
int FileController<T>::GetMaximum()
{
  return FileController<T>::GetMaximum(fMode, fFileName);
}

template <typename T>
int FileController<T>::GetMaximum(TBwaveform fMode_, std::string filename)
{

  FILE *aFile = fopen(filename.c_str(), "rb");
  fseek(aFile, 0L, SEEK_END);
  long long size = ftell(aFile);
  fclose(aFile);
  int nEvent = size / 65536;

  return nEvent;
}

template <typename T>
int FileController<T>::GetMaximum(TBfastmode fMode_, std::string filename)
{

  FILE *aFile = fopen(filename.c_str(), "rb");

  fseek(aFile, 0L, SEEK_END);
  long long size = ftell(aFile);
  fclose(aFile);
  int nEvent = size / 256;

  return nEvent;
}

template <typename T>
void FileController<T>::LiveReadyForNextFile() {

  std::string aFileName = GetFileName();
  fTotalMaxEventNum += GetMaximum(fMode, aFileName);;
}

template <typename T>
bool FileController<T>::CheckSingleNextNextFileExistence() {

  std::string tmpFileName = GetFileName(fMode, fNextFileNum + 1);

  if (access(tmpFileName.c_str(), F_OK))
    return false;

  return true;
}

template <typename T>
bool FileController<T>::CheckSingleNextFileExistence() {

  std::string tmpFileName = GetFileName(fMode, fNextFileNum);
  if (access(tmpFileName.c_str(), F_OK))   
    return false;

  return true;
}

template <typename T>
void FileController<T>::CheckOverflow()
{

  if (fCurrentEventNum == fCurrentMaxEventNum)
  {
    // std::cout << "end of the file!" << std::endl;
    fclose(fRawData);
    OpenFile();
  }
}
template class FileController<TBwaveform>;
template class FileController<TBfastmode>;

template <typename T>
TBmidbase FileController<T>::readMetadata()
{
  char data[64];
  int data_length;
  int run_number;
  int tcb_trig_type;
  int tcb_trig_number;
  long long tcb_trig_time;
  int mid;
  int local_trig_number;
  int local_trigger_pattern;
  long long local_trig_time;
  long long fine_time;
  long long coarse_time;
  int itmp;
  long long ltmp;

  // read header
  fread(data, 1, 64, fRawData);

  // data length
  data_length = data[0] & 0xFF;
  itmp = data[1] & 0xFF;
  itmp = itmp << 8;
  data_length = data_length + itmp;
  itmp = data[2] & 0xFF;
  itmp = itmp << 16;
  data_length = data_length + itmp;
  itmp = data[3] & 0xFF;
  itmp = itmp << 24;
  data_length = data_length + itmp;

  // run number
  run_number = data[4] & 0xFF;
  itmp = data[5] & 0xFF;
  itmp = itmp << 8;
  run_number = run_number + itmp;

  // trigger type
  tcb_trig_type = data[6] & 0xFF;

  // TCB trigger #
  tcb_trig_number = data[7] & 0xFF;
  itmp = data[8] & 0xFF;
  itmp = itmp << 8;
  tcb_trig_number = tcb_trig_number + itmp;
  itmp = data[9] & 0xFF;
  itmp = itmp << 16;
  tcb_trig_number = tcb_trig_number + itmp;
  itmp = data[10] & 0xFF;
  itmp = itmp << 24;
  tcb_trig_number = tcb_trig_number + itmp;

  // TCB trigger time
  fine_time = data[11] & 0xFF;
  fine_time = fine_time * 11; // actually * (1000 / 90)
  coarse_time = data[12] & 0xFF;
  ltmp = data[13] & 0xFF;
  ltmp = ltmp << 8;
  coarse_time = coarse_time + ltmp;
  ltmp = data[14] & 0xFF;
  ltmp = ltmp << 16;
  coarse_time = coarse_time + ltmp;
  ltmp = data[15] & 0xFF;
  ltmp = ltmp << 24;
  coarse_time = coarse_time + ltmp;
  ltmp = data[16] & 0xFF;
  ltmp = ltmp << 32;
  coarse_time = coarse_time + ltmp;
  ltmp = data[17] & 0xFF;
  ltmp = ltmp << 40;
  coarse_time = coarse_time + ltmp;
  coarse_time = coarse_time * 1000; // get ns
  tcb_trig_time = fine_time + coarse_time;

  // mid
  mid = data[18] & 0xFF;

  // local trigger #
  local_trig_number = data[19] & 0xFF;
  itmp = data[20] & 0xFF;
  itmp = itmp << 8;
  local_trig_number = local_trig_number + itmp;
  itmp = data[21] & 0xFF;
  itmp = itmp << 16;
  local_trig_number = local_trig_number + itmp;
  itmp = data[22] & 0xFF;
  itmp = itmp << 24;
  local_trig_number = local_trig_number + itmp;

  // local trigger #
  local_trigger_pattern = data[23] & 0xFF;
  itmp = data[24] & 0xFF;
  itmp = itmp << 8;
  local_trigger_pattern = local_trigger_pattern + itmp;
  itmp = data[25] & 0xFF;
  itmp = itmp << 16;
  local_trigger_pattern = local_trigger_pattern + itmp;
  itmp = data[26] & 0xFF;
  itmp = itmp << 24;
  local_trigger_pattern = local_trigger_pattern + itmp;

  // local trigger time
  fine_time = data[27] & 0xFF;
  fine_time = fine_time * 11; // actually * (1000 / 90)
  coarse_time = data[28] & 0xFF;
  ltmp = data[29] & 0xFF;
  ltmp = ltmp << 8;
  coarse_time = coarse_time + ltmp;
  ltmp = data[30] & 0xFF;
  ltmp = ltmp << 16;
  coarse_time = coarse_time + ltmp;
  ltmp = data[31] & 0xFF;
  ltmp = ltmp << 24;
  coarse_time = coarse_time + ltmp;
  ltmp = data[32] & 0xFF;
  ltmp = ltmp << 32;
  coarse_time = coarse_time + ltmp;
  ltmp = data[33] & 0xFF;
  ltmp = ltmp << 40;
  coarse_time = coarse_time + ltmp;
  coarse_time = coarse_time * 1000; // get ns
  local_trig_time = fine_time + coarse_time;

  auto amid = TBmidbase(tcb_trig_number, run_number, mid);
  amid.setTCB(tcb_trig_type, tcb_trig_number, tcb_trig_time);
  amid.setLocal(local_trig_number, local_trigger_pattern, local_trig_time);

  return std::move(amid);
}

template <typename T>
TBmid<TBwaveform> FileController<T>::ReadWaveformMid()
{
  const auto base = readMetadata();

  short adc[32736];

  // read waveform
  fread(adc, 2, 32736, fRawData);

  unsigned channelsize = 32;

  auto amid = TBmid<TBwaveform>(base);
  std::vector<TBwaveform> waveforms;
  waveforms.reserve(channelsize);

  for (unsigned int idx = 0; idx < channelsize; idx++)
  {
    auto awave = TBwaveform();
    awave.setChannel(idx + 1); // WARNING channel number 1 - 32
    awave.init();
    waveforms.emplace_back(awave);
  }

  // fill waveform for channel
  for (int i = 0; i < 1024; i++)
  {
    for (unsigned int idx = 0; idx < channelsize; idx++)
      waveforms.at(idx).fill(i, adc[i * 32 + idx]); // should be always 32 here
  }

  amid.setChannels(waveforms);

  return std::move(amid);
}

template <typename T>
TBmid<TBfastmode> FileController<T>::ReadFastmodeMid()
{
  const auto base = readMetadata();

  short data[96];
  int energy;
  int timing;

  // read fast data
  fread(data, 2, 96, fRawData);

  unsigned int channelsize = 32;

  auto amid = TBmid<TBfastmode>(base);
  std::vector<TBfastmode> fastmodes;
  fastmodes.reserve(channelsize);

  for (unsigned int idx = 0; idx < channelsize; idx++)
  {
    auto afast = TBfastmode();
    afast.setChannel(idx + 1); // WARNING channel number 1 - 32

    // fill waveform for channel to plot
    energy = data[idx * 3 + 1] & 0xFFFF;
    energy = energy * 65536;
    energy = energy + (data[idx * 3] & 0xFFFF);

    timing = data[idx * 3 + 2] & 0xFFFF;

    afast.setAdc(energy);
    afast.setTiming(timing);

    fastmodes.emplace_back(afast);
  }

  amid.setChannels(fastmodes);

  return std::move(amid);
}

template <typename T>
TBread<T>::TBread(int fRunNum_, int fMaxEvent_, int fMaxFile_, bool fIsLive_, std::string fBaseDir_, std::vector<int> fMIDMap_)
    : fRunNum(fRunNum_), fMaxEvent(fMaxEvent_), fMaxFile(fMaxFile_), fCurrentEvent(0), fIsLive(fIsLive_), fBaseDir(fBaseDir_), fMIDMap(fMIDMap_)
{
  ANSI = ANSI_CODE();
  if (fMaxFile == -1)
    fMaxFile = 999;

  if (fIsLive)
    fMaxFile = 1;

  if (!fIsLive) init();
  else          init_live();
}

template <typename T>
void TBread<T>::init()
{

  fFileMap.clear();

  for (auto aMid : fMIDMap)
    fFileMap.insert(std::make_pair(aMid, new FileController<T>(fRunNum, fIsLive, aMid, fBaseDir, fMaxFile)));

  int tmpMax = 99999999;
  for (int i = 0; i < fMIDMap.size(); i++)
    if (tmpMax > fFileMap.at(fMIDMap.at(i))->GetTotalMaxEventNum())
      tmpMax = fFileMap.at(fMIDMap.at(i))->GetTotalMaxEventNum();

  if (fMaxEvent == -1)
  {
    std::cout << " Maximum Event # is set to " << tmpMax << std::endl;
    fMaxEvent = tmpMax;
  }

  if (fMaxEvent > tmpMax)
  {
    std::cout << " Input Maximum Event # : " << fMaxEvent << " is larger than maximum of input file : " << tmpMax << " ! " << std::endl;
    std::cout << " Maximum Event # is set to " << tmpMax << std::endl;
    fMaxEvent = tmpMax;
  }
}

template <typename T>
void TBread<T>::init_live()
{
  fFileMap.clear();

  for (auto aMid : fMIDMap)
    fFileMap.insert(std::make_pair(aMid, new FileController<T>(fRunNum, fIsLive, aMid, fBaseDir, fMaxFile)));

}

template <typename T>
bool TBread<T>::CheckNextFileExistence()
{

  std::cout << "                                       |";
  for (int i = 0; i < fMIDMap.size(); i++) {
    if (fMIDMap.at(i) >= 10) std::cout << " MID" + std::to_string(fMIDMap.at(i)) + " |";
    else                     std::cout << " MID " + std::to_string(fMIDMap.at(i)) + " |";
  }
  std::cout << " " << std::endl;

  std::cout << "---------------------------------------";
  for (int i = 0; i < fMIDMap.size(); i++) {
    std::cout << "--------";
  }
  std::cout << "-" << std::endl;

  // Sentinel path is relative to monit's cwd (Python invokes with cwd=DQM dir,
  // so JSON output and sentinel both live under ./output/).
  std::string sentinelPath = "./output/Run" + std::to_string(fRunNum) + "_END";

  while(1) {

    std::time_t tNowClock = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());

    std::string tNow(30, '\0');
    std::strftime(&tNow[0], tNow.size(), "%Y-%m-%d %H:%M:%S", std::localtime(&tNowClock));

    std::cout << "Waiting for file : " << ANSI.YELLOW + ANSI.BOLD + tNow + ANSI.END + " ";

    bool sentinel = (access(sentinelPath.c_str(), F_OK) == 0);

    bool ready = true;
    bool anyHasNext = false;
    for (int i = 0; i < fMIDMap.size(); i++) {
      bool hasNext = fFileMap.at(fMIDMap.at(i))->CheckSingleNextFileExistence();
      bool hasNextNext = fFileMap.at(fMIDMap.at(i))->CheckSingleNextNextFileExistence();

      // When the sentinel is present, accept "next exists" without requiring
      // next-next — DAQ has stopped so no further files will appear and the
      // current next file is already complete.
      bool isReady = sentinel ? hasNext : (hasNext && hasNextNext);
      ready = ready && isReady;
      if (hasNext) anyHasNext = true;

      if(isReady) std::cout << "|   " + ANSI.GREEN + ANSI.BOLD + "O   " + ANSI.END;
      else        std::cout << "|   " + ANSI.RED + ANSI.BOLD + "X   " + ANSI.END;
    }
    std::cout << "|" << std::endl;

    if (ready) {
      for (int i = 0; i < fMIDMap.size(); i++)
        fFileMap.at(fMIDMap.at(i))->LiveReadyForNextFile();

      std::cout << ANSI.BOLD + ANSI.UNDERLINE_THICK + "Files are ready, updating plots." + ANSI.END << std::endl;
      return true;
    }

    if (sentinel && !anyHasNext) {
      std::cout << ANSI.BOLD + ANSI.YELLOW + "DAQ end sentinel observed, no more data — exiting LIVE." + ANSI.END << std::endl;
      return false;
    }

    gSystem->Sleep(5000);
  }
}

template <typename T>
TBevt<T> TBread<T>::GetAnEvent()
{

  TBevt<T> returnEvt;
  std::map<int, TBmid<T>> anEvent;
  for (int i = 0; i < fMIDMap.size(); i++)
    anEvent.insert(std::make_pair(fMIDMap.at(i), fFileMap.at(fMIDMap.at(i))->ReadEvent()));

  int ref_event_num = anEvent.at(fMIDMap.at(0)).evt();
  for (int i = 1; i < fMIDMap.size(); i++) 
    if (anEvent.at(fMIDMap.at(i)).evt() != ref_event_num)
      throw std::runtime_error(ANSI.RED + ANSI.BOLD + "TBread<T>::GetAnEvent() - event num does not match between MIDs : " + std::to_string(fMIDMap.at(i)) + ANSI.END);
  
  returnEvt.Set(anEvent);

  fCurrentEvent++;
  return std::move(returnEvt);
}

template <typename T>
int TBread<T>::GetLiveMaxEvent() {

  int tmpMax = 99999999;
  for (int i = 0; i < fMIDMap.size(); i++)
    if (tmpMax > fFileMap.at(fMIDMap.at(i))->GetTotalMaxEventNum())
      tmpMax = fFileMap.at(fMIDMap.at(i))->GetTotalMaxEventNum();

  return tmpMax;
}

template <typename T>
int TBread<T>::GetLiveCurrentEvent() {

  int tmpMax = 99999999;
  for (int i = 0; i < fMIDMap.size(); i++)
    if (tmpMax > fFileMap.at(fMIDMap.at(i))->GetTotalEventNum())
      tmpMax = fFileMap.at(fMIDMap.at(i))->GetTotalEventNum();

  return tmpMax;
}

template class TBread<TBwaveform>;
template class TBread<TBfastmode>;
