#include "DataLoader.hpp"
#include "Bar.hpp"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <exception>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/types.h>
#include <unordered_map>
#include <vector>

namespace {
std::vector<std::string> spiltCSVLine(const std::string &line) {
  std::vector<std::string> fields;
  std::stringstream stream(line);

  std::string field;

  while (std::getline(stream, field, ',')) {
    fields.push_back(field);
  }

  return fields;
}

std::string normalizeHeader(std::string value) {
  value.erase(std::remove_if(value.begin(), value.end(),
                             [](unsigned char c) { return std::isspace(c); }),
              value.end());

  std::transform(
      value.begin(), value.end(), value.begin(),
      [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

  return value;
}
} // namespace

std::vector<Bar> DataLoader::loadCSV(const std::string &filePath) {
  std::ifstream file(filePath);

  if (!file.is_open()) {
    throw std::runtime_error("Could not open CSV file: " + filePath);
  }

  std::string headerLine;

  if (!std::getline(file, headerLine)) {
    throw std::runtime_error("Could not read CSV header: " + filePath);
  }

  const auto headers = spiltCSVLine(headerLine);

  std::unordered_map<std::string, std::size_t> column;

  for (std::size_t i{0}; i < headers.size(); ++i) {
    column[normalizeHeader(headers[i])] = i;
  }

  // Test for the exsistence of all Bars properly

  const std::vector<std::string> requiredColumns{"date", "open",  "high",
                                                 "low",  "close", "volume"};

  for (const auto &name : requiredColumns) {
    if (column.find(name) == column.end()) {
      throw std::runtime_error("Missing required CSV column: " + name);
    }
  }

  std::vector<Bar> bars;
  std::string line;
  std::size_t lineNumber = 1;

  while (std::getline(file, line)) {
    ++lineNumber;

    if (line.empty()) {
      continue;
    }

    const auto fields = spiltCSVLine(line);

    try {
      Bar bar;

      bar.date = fields.at(column.at("date"));
      bar.open = std::stod(fields.at(column.at("open")));
      bar.high = std::stod(fields.at(column.at("high")));
      bar.low = std::stod(fields.at(column.at("low")));
      bar.close = std::stod(fields.at(column.at("close")));
      bar.volume = std::stod(fields.at(column.at("volume")));

      bars.push_back(bar);
    }

    catch (const std::exception &e) {
      throw std::runtime_error("Error parsing CSV line" +
                               std::to_string(lineNumber) + ": " + e.what());
    }
  }

  std::sort(bars.begin(), bars.end(),
            [](const Bar &a, const Bar &b) { return a.date < b.date; });

  return bars;
}
