#include "Backtester.hpp"
#include "Portfolio.hpp"

#include <stdexcept>
#include <utility>

Backtester::Backtester(std::vector<Bar> bars, Strategy &strategy,
                       double initialCash)
    : bars(std::move(bars)), strategy(strategy), portfolio(initialCash) {}

void Backtester::executeBuy(const Bar &bar) {
  if (portfolio.position != 0)
    return;
  if (bar.open <= 0.0)
    return;

  const int quantity = static_cast<int>(portfolio.cash / bar.open);

  if (quantity <= 0)
    return;

  const double cost = static_cast<double>(quantity) * bar.open;

  portfolio.cash -= cost;
  portfolio.position = quantity;

  portfolio.trades.push_back(Trade{bar.date, "BUY", bar.open, quantity});
}

void Backtester::executeSell(const Bar &bar) {
  if (portfolio.position == 0) {
    return;
  }

  const int quantity = portfolio.position;

  const double proceeds = static_cast<double>(quantity) * bar.open;

  portfolio.cash += proceeds;
  portfolio.position = 0;

  portfolio.trades.push_back(Trade{bar.date, "SELL", bar.open, quantity});
}

void Backtester::run() {
  Signal pendingSignal = Signal::HOLD;

  for (std::size_t i{0}; i < bars.size(); ++i) {
    const Bar &currentBar = bars[i];

    if (i > 0) {
      if (pendingSignal == Signal::BUY) {
        executeBuy(currentBar);
      } else if (pendingSignal == Signal::SELL) {
        executeBuy(currentBar);
      }
    }

    portfolio.equityCurve.push_back(
        EquityPoint{currentBar.date, portfolio.equity(currentBar.close)});

    if (i + 1 < bars.size()) {
      pendingSignal = strategy.generateSignal(bars, i);
    }
  }
}

const Portfolio &Backtester::getPortfolio() const { return portfolio; }
