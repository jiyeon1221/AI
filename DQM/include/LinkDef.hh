#include "TBmid.h"

#if defined(__CLING__) || defined(__CINT__)
#pragma link off all globals;
#pragma link off all classes;
#pragma link off all functions;

#pragma link C++ class TBcid + ;
#pragma link C++ class TBwaveform + ;
#pragma link C++ class TBfastmode + ;

#pragma link C++ class TBread < TBwaveform> + ;
#pragma link C++ class TBread < TBfastmode> + ;

#pragma link C++ class TBmidbase + ;
#pragma link C++ class TBmid < TBwaveform> + ;
#pragma link C++ class TBmid < TBfastmode> + ;
#pragma link C++ class TBevt < TBwaveform> + ;
#pragma link C++ class TBevt < TBfastmode> + ;

#pragma link C++ class TBmonit < TBwaveform> + ;
#pragma link C++ class TBmonit < TBfastmode> + ;

#endif
