#pragma once

#include "Strategy.hpp"

#include <cstddef>
#include <iterator>
#include <vector>

class SmaCross : public Strategy {
private:
  std::size_t shortWindow;
  std::size_t longWindow;

  double calculateSMA(const std::vector<Bar> &bars, std::size_t endIndex,
                      std::size_t window) const;

public:
  SmaCross(std::size_t shortWindow, std::size_t longWindow);

  Signal generateSignal(const std::vector<Bar> &bars,
                        std::size_t currentIndex) override;
};
