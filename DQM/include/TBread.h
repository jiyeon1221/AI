#ifndef TBread_h
#define TBread_h 1

#ifndef _WIN32
#include <unistd.h>
#endif

#include "TBmid.h"
#include "TBevt.h"
#include <string>

class ANSI_CODE {

public:
  ANSI_CODE() {}
  ~ANSI_CODE() {}

  // control
  std::string END = "\033[0m";

  // styles
  std::string BOLD = "\033[1m";
  std::string ITALIC = "\033[3m";
  std::string UNDERLINE = "\033[4m";
  std::string UNDERLINE_THICK = "\033[21m";
  std::string STRIKE_THROUGH = "\033[9m";
  std::string MARGIN_1 = "\033[51m";
  std::string MARGIN_2 = "\033[52m";

  // bg
  std::string HIGHLIGHTED = "\033[7m";
  std::string HIGHLIGHTED_BLACK = "\033[40m";
  std::string HIGHLIGHTED_RED = "\033[41m";
  std::string HIGHLIGHTED_GREEN = "\033[42m";
  std::string HIGHLIGHTED_YELLOW = "\033[43m";
  std::string HIGHLIGHTED_BLUE = "\033[44m";
  std::string HIGHLIGHTED_PURPLE = "\033[45m";
  std::string HIGHLIGHTED_CYAN = "\033[46m";
  std::string HIGHLIGHTED_GREY = "\033[47m";
  std::string HIGHLIGHTED_GREY_LIGHT = "\033[100m";
  std::string HIGHLIGHTED_RED_LIGHT = "\033[101m";
  std::string HIGHLIGHTED_GREEN_LIGHT = "\033[102m";
  std::string HIGHLIGHTED_YELLOW_LIGHT = "\033[103m";
  std::string HIGHLIGHTED_BLUE_LIGHT = "\033[104m";
  std::string HIGHLIGHTED_PURPLE_LIGHT = "\033[105m";
  std::string HIGHLIGHTED_CYAN_LIGHT = "\033[106m";
  std::string HIGHLIGHTED_WHITE_LIGHT = "\033[107m";

  // fg
  std::string BLACK = "\033[30m";
  std::string RED_DARK = "\033[31m";
  std::string GREEN_DARK = "\033[32m";
  std::string YELLOW_DARK = "\033[33m";
  std::string BLUE_DARK = "\033[34m";
  std::string PURPLE_DARK = "\033[35m";
  std::string CYAN_DARK = "\033[36m";
  std::string GREY_DARK = "\033[37m";
  std::string BLACK_LIGHT = "\033[90m";
  std::string RED = "\033[91m";
  std::string GREEN = "\033[92m";
  std::string YELLOW = "\033[93m";
  std::string BLUE = "\033[94m";
  std::string PURPLE = "\033[95m";
  std::string CYAN = "\033[96m";
  std::string WHITE = "\033[97m";
};

template <class T>
class FileController
{
public:
  FileController(int fRunNum_, bool fIsLive_, int fMID_, std::string fBaseDir_, int fMaxFileNum_);
  ~FileController()
  {
    fclose(fRawData);
  }

  TBmid<TBwaveform> ReadWaveformMid();
  TBmid<TBfastmode> ReadFastmodeMid();

  std::string GetFileName();
  std::string GetFileName(TBwaveform fMode_, int aFileNum);
  std::string GetFileName(TBfastmode fMode_, int aFileNum);

  std::string GetCurrentFileName() { return fFileName; }
  int GetMidNum() { return fMID; }
  int GetRunNum() { return fRunNum; }

  int GetCurrentMaxEvent() { return fCurrentMaxEventNum; }
  int GetCurrentEventNum() { return fCurrentEventNum; }
  int GetTotalEventNum() { return fTotalEventNum; }
  int GetTotalMaxEventNum() { return fTotalMaxEventNum; }
  int GetNextFileNum() { return fNextFileNum; }

  void OpenFile();
  TBmid<T> ReadEvent();
  TBmid<TBwaveform> ReadEvent(TBwaveform fMode_);
  TBmid<TBfastmode> ReadEvent(TBfastmode fMode_);

  void CheckOverflow();

  int GetMaximum();
  int GetMaximum(TBwaveform fMode_, std::string filename);
  int GetMaximum(TBfastmode fMode_, std::string filename);

  bool CheckSingleNextNextFileExistence();
  bool CheckSingleNextFileExistence();

  void LiveReadyForNextFile();

private:
  void init();

  T fMode;

  FILE *fRawData;
  TBmidbase readMetadata();

  ANSI_CODE ANSI;

  std::string fFileName;
  std::string fBaseDir;
  int fRunNum;
  bool fIsLive;
  int fMID;
  int fNextFileNum;
  int fMaxFileNum;

  int fTotalEventNum;
  int fCurrentEventNum;
  int fTotalMaxEventNum;
  int fCurrentMaxEventNum;
};

template <class T>
class TBread
{
public:
  TBread(int fRunNum_, int fMaxEvent_, int fMaxFile_, bool fIsLive_, std::string fBaseDir_, std::vector<int> fMIDMap_);
  ~TBread() {}

  TBevt<T> GetAnEvent();
  int GetMaxEvent() { return fMaxEvent; }
  int GetCurrentEvent() { return fCurrentEvent; }
  int GetLiveMaxEvent();
  int GetLiveCurrentEvent();
  void CheckNextFileExistence();

private:
  void init();
  void init_live();

  ANSI_CODE ANSI;

  int fRunNum;
  int fMaxEvent;
  int fMaxFile;
  int fCurrentEvent;
  bool fIsLive;
  std::string fBaseDir;

  std::vector<int> fMIDMap;

  std::map<int, FileController<T> *> fFileMap;
};

#endif
