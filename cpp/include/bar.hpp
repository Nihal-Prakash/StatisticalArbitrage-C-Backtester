#pragma once

#include <cstdint>
#include <string>

struct Bar {
  std::string date;

  double open;
  double high;
  double low;
  double close;

  std::int64_t volume;
};
