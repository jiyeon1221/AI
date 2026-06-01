#include "TBevt.h"

template <typename T>
TBevt<T>::TBevt()
    : fEvent(0)
{
  fMapMids.clear();
}

template <typename T>
const T TBevt<T>::GetData(const TBcid &cid) const
{
  T adata = T();

  for (const auto &aMid : fMapMids)
  {
    if (aMid.second.mid() == cid.mid())
    {
      adata = aMid.second.channel(cid.channel() - 1); // WARNING channel number 1 - 32
      break;
    }
  }

  return adata;
}

template <typename T>
TBmid<T> TBevt<T>::Mid(unsigned idx) const
{

  if (fMapMids.find(idx) == fMapMids.end())
    throw std::runtime_error("TBevt::Mid - mid is defined");

  return fMapMids.find(idx)->second;
}

template class TBevt<TBwaveform>;
template class TBevt<TBfastmode>;
