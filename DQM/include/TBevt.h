#ifndef TBevt_h
#define TBevt_h 1

#include <vector>
#include <map>

#include "TBmid.h"
#include "TBdetector.h"

template <class T>
class TBevt
{
public:
  TBevt();
  ~TBevt() {}

  void Set(std::map<int, TBmid<T>> fMapMids_) { fMapMids = fMapMids_; }
  void SetEvent(int fEvent_) { fEvent = fEvent_; }

  void Print() {
    std::cout << "Total size : " << Size() << std::endl;
    for (auto aMap : fMapMids)
      std::cout << aMap.first << " " << aMap.second.mid() << std::endl;
  }

  int GetEventNum() { return fEvent; }

  // TBmid<T> Mid(unsigned idx) const { return mids_.at(idx); }
  TBmid<T> Mid(unsigned idx) const;
  int Size() const { return static_cast<int>(fMapMids.size()); }

  const T GetData(const TBcid &cid) const;

private:
  int fEvent;
  std::map<int, TBmid<T>> fMapMids;
  // std::vector<TBmid<T>> mids_;
};

#endif
