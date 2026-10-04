#pragma once

#include "Bar.hpp"

#include <string>
#include <vector>

class DataLoader {
public:
  static std::vector<Bar> loadCSV(const std::string &filePath);
};
