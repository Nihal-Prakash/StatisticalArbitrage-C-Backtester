#include "data/DataLoader.hpp"
#include "engine/Backtester.hpp"
#include "engine/PerformanceMetrics.hpp"
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

    const PerformanceMetrics metrics =
        PreformanceAnalyzer::calculate(portfolio);

    std::cout << "Initial capital: " << metrics.initialCapital << '\n';

    std::cout << "Final equity: " << metrics.finalEquity << '\n';

    std::cout << "Absolute P&L: " << metrics.absolutePnL << '\n';

    std::cout << "Total return: " << metrics.totalReturn * 100.0 << "%\n";

    std::cout << "Executed trades: " << metrics.tradeCount << '\n';

    std::cout << "Max drawdown: " << metrics.maxDrawndown * 100.0 << "%\n";

    std::cout << "Final cash: " << portfolio.cash << '\n';

    std::cout << "Position: " << portfolio.position << '\n';

    std::cout << "Trades: " << portfolio.trades.size() << '\n';

    for (const Trade &trade : portfolio.trades) {
      std::cout << trade.date << ' ' << trade.side << " qty=" << trade.quantity
                << " price=" << trade.price << " cash_after=" << trade.cashAfter
                << " position_after=" << trade.positionAfter << '\n';
    }

    const EquityPoint &finalPoint = portfolio.equityCurve.back();

    std::cout << "Final mark price: " << finalPoint.marketPrice << '\n';
  } catch (const std::exception &e) {
    std::cerr << "ERROR: " << e.what() << '\n';

    return 1;
  }

  return 0;
}
