
#include <cstdio>
#include <iostream>
#include "TBmonit.h"
#include "TBobject.h"
#include "TBsingleWaveform.h"

int main(int argc, char* argv[]) {

  // C와 C++ 출력을 즉시 비워 웹 UI에 진행 상황을 전달한다.
  std::setvbuf(stdout, nullptr, _IONBF, 0);
  std::setvbuf(stderr, nullptr, _IONBF, 0);
  std::cout << std::unitbuf;
  std::cerr << std::unitbuf;

  ObjectCollection* obj = new ObjectCollection(argc, argv);
  if (obj->Help())
    return 1;


  std::string aCase;
  obj->GetVariable("type", &aCase);

  std::string aMethod;
  obj->GetVariable("method", &aMethod);

  if (aCase == "single" && aMethod == "Waveform") {
  
    TBsingleWaveform* singleWaveform = new TBsingleWaveform(std::move(obj));
    singleWaveform->Loop();
  } else {
    
    TBmonit<TBwaveform>* monit = new TBmonit<TBwaveform>(std::move(obj));
    monit->Loop();
  }

  return 0;
}
