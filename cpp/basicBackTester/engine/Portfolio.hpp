#pragma once

#include <string>
#include <vector>

struct Trade {
  std::string date;
  std::string side;

  double price;
  int quantity;

  double cashAfter;
  int positionAfter;
};

struct EquityPoint {
  std::string date;

  int position;
  double cash;
  double marketPrice;
  double equity;
};

struct Portfolio {
  double initialCash;
  double cash;
  int position = 0;

  std::vector<Trade> trades;
  std::vector<EquityPoint> equityCurve;

  explicit Portfolio(double startingCash)
      : initialCash(startingCash), cash(startingCash) {}

  double equity(double currentPrice) const {
    return cash + static_cast<double>(position) * currentPrice;
  }
};
