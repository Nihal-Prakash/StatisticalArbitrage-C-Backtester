cmake_minimum_required(VERSION 3.16)

project(stat_arb LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(backtester
    cpp/src/main.cpp
)
