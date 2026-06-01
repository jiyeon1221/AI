
#include <cstdio>
#include <iostream>
#include "TBmonit.h"
#include "TBobject.h"
#include "TBsingleWaveform.h"

int main(int argc, char* argv[]) {

  // Force unbuffered stdout/stderr so progress prints reach the web UI
  // in real time when stdout is a pipe (subprocess.PIPE in server.py).
  //
  // Background: default C-runtime behaviour for non-TTY stdout on macOS
  // is full buffering (~4 KB), which makes monit's per-10-event
  // progress lines pile up in the buffer for many seconds before being
  // flushed — the "stuck at 4510" symptom on the freeform DQM page.
  //
  // Why _IONBF (unbuffered) instead of _IOLBF (line-buffered):
  // macOS / BSD libc has a quirk where setvbuf(..., _IOLBF, 0) does
  // NOT actually switch to line-buffered mode reliably (it can stay
  // fully buffered). Passing _IONBF is unambiguous: every write goes
  // straight to the pipe. The throughput cost is negligible because
  // monit only writes ~10 short lines per second from the event loop.
  //
  // Why both the C-runtime (setvbuf) AND C++ (std::unitbuf):
  //   - setvbuf affects the FILE* used by printf / fwrite (the
  //     printf in GetFormattedRamInfo).
  //   - std::unitbuf flushes std::cout after every << operation, so
  //     mixed-stream output (cout + printf in the same progress line)
  //     reaches the pipe with no extra fflush calls.
  // Together they make stdout behave the same whether the user runs
  // monit directly in a terminal or via the web UI subprocess.
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
