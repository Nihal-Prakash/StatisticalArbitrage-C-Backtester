#pragma once

#include "../data/Bar.hpp"

#include <cstddef>
#include <vector>

enum class Signal { BUY, SELL, HOLD };

class Strategy {
public:
  virtual Signal generateSignal(const std::vector<Bar> &bars,
                                std::size_t currentIndex) = 0;

  virtual ~Strategy() = default;
};
