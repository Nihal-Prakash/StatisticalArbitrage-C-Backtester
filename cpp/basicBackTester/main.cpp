#include "data/DataLoader.hpp"
#include "engine/Backtester.hpp"
#include "strategy/SmaCross.hpp"

#include <iostream>

int main() {
  try {
    auto bars = DataLoader::loadCSV("../../datasets/raw/RELIANCE.NS.csv");

    std::cout << "Bars Loaded: " << bars.size() << "\n";

    SmaCross strategy(3, 5);
    std::cout << "Bars loaded: " << bars.size() << '\n';

    std::cout << "First: " << bars.front().date
              << " close=" << bars.front().close << '\n';

    std::cout << "Last: " << bars.back().date << " close=" << bars.back().close
              << '\n';

    Backtester backtester(std::move(bars), strategy, 100000.0);

    backtester.run();

    const Portfolio &portfolio = backtester.getPortfolio();

    std::cout << "Final cash: " << portfolio.cash << '\n';

    std::cout << "Position: " << portfolio.position << '\n';

    std::cout << "Trades: " << portfolio.trades.size() << '\n';

    std::cout << "Final equity: " << portfolio.equityCurve.back().equity
              << '\n';
  } catch (const std::exception &e) {
    std::cerr << "ERROR: " << e.what() << '\n';

    return 1;
  }

  return 0;
}
