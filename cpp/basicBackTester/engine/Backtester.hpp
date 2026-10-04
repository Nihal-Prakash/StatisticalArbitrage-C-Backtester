#pragma once

#include "../data/Bar.hpp"
#include "../strategy/Strategy.hpp"
#include "Portfolio.hpp"

#include <vector>

class Backtester {
private:
  std::vector<Bar> bars;

  Strategy &strategy;
  Portfolio portfolio;

  void executeBuy(const Bar &bar);

  void executeSell(const Bar &bar);

public:
  Backtester(std::vector<Bar> bars, Strategy &strategy, double initialCash);

  void run();

  const Portfolio &getPortfolio() const;
};
