#include <limits.h>

#include "TBdetector.h"

TBcid::TBcid(int midin, int channelin)
    : mid_(midin), channel_(channelin) {}

TBcid::TBcid()
    : mid_(0), channel_(0) {}

bool TBcid::operator<(const TBcid &rh) const
{
  if (mid_ != rh.mid())
    return mid_ < rh.mid();

  return channel_ < rh.channel();
}

bool TBcid::operator==(const TBcid &rh) const
{
  return (channel_ == rh.channel()) && (mid_ == rh.mid());
}

void TBcid::print() const
{
  std::cout << "TBcid::mid()=" << mid_ << " TBcid::channel()=" << channel_ << std::endl;
}

TBdetector::TBdetector()
    : det_(TBdetector::detid::nulldet), id_(0) {}

TBdetector::TBdetector(TBdetector::detid in)
    : det_(in), id_(0) {}

void TBdetector::encodeModule(int mod, int tow, bool isc)
{
  uint32_t mod32 = static_cast<uint32_t>(mod) << 2 * sizeof(uint8_t) * CHAR_BIT;
  uint32_t tow32 = static_cast<uint32_t>(tow) << sizeof(uint8_t) * CHAR_BIT;
  uint32_t isc32 = static_cast<uint32_t>(isc);

  uint32_t val = mod32 | tow32 | isc32;
  uint64_t val64 = static_cast<uint64_t>(val) << sizeof(uint32_t) * CHAR_BIT;

  id_ = id_ & 0x00000000FFFFFFFF;
  id_ = val64 | id_;
}

void TBdetector::encodeMultiCh(int row, int column)
{
  uint32_t plate32 = static_cast<uint32_t>(row) << sizeof(uint16_t) * CHAR_BIT;
  uint32_t column32 = static_cast<uint32_t>(column);

  uint32_t val = plate32 | column32;
  uint64_t val64 = static_cast<uint64_t>(val);

  id_ = id_ & 0xFFFFFFFF00000000;
  id_ = val64 | id_;
}

void TBdetector::encodeColumn(int column)
{
  uint64_t val64 = static_cast<uint64_t>(static_cast<uint16_t>(column));

  id_ = id_ & 0xFFFFFFFFFFFF0000;
  id_ = val64 | id_;
}

// hard-coded!!!
int TBdetector::module() const
{
  uint64_t val64 = id_ & 0x00FF000000000000;
  return static_cast<int>(val64 >> 6 * sizeof(uint8_t) * CHAR_BIT);
}

int TBdetector::tower() const
{
  uint64_t val64 = id_ & 0x0000FF0000000000;
  return static_cast<int>(val64 >> 5 * sizeof(uint8_t) * CHAR_BIT);
}

bool TBdetector::isCeren() const
{
  uint64_t val64 = id_ & 0x000000FF00000000;
  return static_cast<bool>(val64 >> 4 * sizeof(uint8_t) * CHAR_BIT);
}

int TBdetector::row() const
{
  uint64_t val64 = id_ & 0x00000000FFFF0000;
  return static_cast<int>(val64 >> sizeof(uint16_t) * CHAR_BIT);
}

int TBdetector::column() const
{
  uint64_t val64 = id_ & 0x000000000000FFFF;
  return static_cast<int>(val64);
}
