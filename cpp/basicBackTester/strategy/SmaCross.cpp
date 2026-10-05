#include "SmaCross.hpp"

#include <stdexcept>

SmaCross::SmaCross(std::size_t shortWindow, std::size_t longWindow)
    : shortWindow(shortWindow), longWindow(longWindow)

{
  if (shortWindow == 0 || longWindow == 0) {
    throw std::invalid_argument("SMA windows must be greater than 0\n");
  }

  if (shortWindow >= longWindow) {
    throw std::invalid_argument(
        "Short window must be smaller than greater window\n");
  }
}

double SmaCross::calculateSMA(const std::vector<Bar> &bars,
                              std::size_t endIndex, std::size_t window) const

{
  double sum = 0.0;

  const std::size_t start = endIndex + 1 - window;

  for (std::size_t i = start; i <= endIndex; ++i) {
    sum += bars[i].close;
  }

  return sum / static_cast<double>(window);
}

Signal SmaCross::generateSignal(const std::vector<Bar> &bars,
                                std::size_t currentIndex) {
  if (currentIndex < longWindow) {
    return Signal::HOLD;
  }

  const double shortPrevious =
      calculateSMA(bars, currentIndex - 1, shortWindow);
  const double longPrevious = calculateSMA(bars, currentIndex - 1, longWindow);
  const double shortCurrent = calculateSMA(bars, currentIndex, shortWindow);
  const double longCurrent = calculateSMA(bars, currentIndex, longWindow);

  if (shortPrevious <= longPrevious && shortCurrent > longCurrent) {
    return Signal::BUY;
  }
  if (shortPrevious >= longPrevious && shortCurrent < longCurrent) {
    return Signal::SELL;
  }

  return Signal::HOLD;
}
