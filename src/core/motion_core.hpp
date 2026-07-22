#pragma once

#include "replay_planner.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace g1_motion {

using replay_planner::ControlledPose;
using replay_planner::SelectNearestEntryIndex;
using replay_planner::SelectNearestExitIndex;

constexpr std::size_t kCsvColumns = 36;
constexpr std::array<int, 17> kMotorIndices = {
    15, 16, 17, 18, 19, 20, 21,
    22, 23, 24, 25, 26, 27, 28,
    12, 13, 14};
constexpr std::array<int, 17> kCsvColumnsForMotors = {
    22, 23, 24, 25, 26, 27, 28,
    29, 30, 31, 32, 33, 34, 35,
    19, 20, 21};

inline std::vector<ControlledPose> LoadCsv(const std::string &path,
                                           float max_abs_angle = 6.5F) {
  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error("cannot open CSV: " + path);
  }

  std::vector<ControlledPose> frames;
  std::string line;
  std::size_t line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    if (line.empty()) {
      continue;
    }
    std::stringstream stream(line);
    std::vector<float> values;
    std::string field;
    bool numeric = true;
    while (std::getline(stream, field, ',')) {
      try {
        std::size_t parsed = 0;
        const float value = std::stof(field, &parsed);
        if (parsed != field.find_last_not_of(" \t\r") + 1 || !std::isfinite(value)) {
          numeric = false;
          break;
        }
        values.push_back(value);
      } catch (const std::exception &) {
        numeric = false;
        break;
      }
    }
    if (!numeric && frames.empty()) {
      continue;  // Optional header.
    }
    if (!numeric || values.size() != kCsvColumns) {
      throw std::runtime_error("invalid CSV row " + std::to_string(line_number) +
                               ": expected 36 finite numeric columns");
    }

    ControlledPose pose{};
    for (std::size_t i = 0; i < pose.size(); ++i) {
      pose[i] = values.at(kCsvColumnsForMotors[i]);
      if (std::abs(pose[i]) > max_abs_angle) {
        throw std::runtime_error("unsafe angle at CSV row " +
                                 std::to_string(line_number));
      }
    }
    frames.push_back(pose);
  }
  if (frames.empty()) {
    throw std::runtime_error("CSV contains no motion frames");
  }
  return frames;
}

inline ControlledPose ClampVelocity(const ControlledPose &from,
                                    const ControlledPose &target,
                                    float max_velocity, float dt) {
  ControlledPose result{};
  const float limit = max_velocity * dt;
  for (std::size_t i = 0; i < result.size(); ++i) {
    result[i] = from[i] + std::clamp(target[i] - from[i], -limit, limit);
  }
  return result;
}

inline bool PoseReached(const ControlledPose &a, const ControlledPose &b,
                        float tolerance = 1.0e-4F) {
  for (std::size_t i = 0; i < a.size(); ++i) {
    if (std::abs(a[i] - b[i]) > tolerance) {
      return false;
    }
  }
  return true;
}

inline std::size_t SelectNearestPoseInRange(
    const ControlledPose &current, const std::vector<ControlledPose> &frames,
    std::size_t begin, std::size_t end) {
  if (frames.empty()) {
    throw std::invalid_argument("cannot select a pose from empty frames");
  }
  begin = std::min(begin, frames.size() - 1);
  end = std::min(end, frames.size());
  if (begin >= end) {
    return begin;
  }
  std::size_t best = begin;
  float best_cost = replay_planner::PoseCost(current, frames[begin]);
  for (std::size_t i = begin + 1; i < end; ++i) {
    const float cost = replay_planner::PoseCost(current, frames[i]);
    if (cost < best_cost) {
      best = i;
      best_cost = cost;
    }
  }
  return best;
}

inline std::size_t SelectNearestEntryIndex(
    const ControlledPose &current, const std::vector<ControlledPose> &frames,
    float fps, float window_seconds) {
  const std::size_t window =
      replay_planner::WindowFrameCount(fps, window_seconds, frames.size());
  return SelectNearestPoseInRange(current, frames, 0, window);
}

inline std::size_t SelectNearestExitIndex(
    const ControlledPose &current, const std::vector<ControlledPose> &frames,
    float fps, float window_seconds, std::size_t entry_index) {
  const std::size_t window =
      replay_planner::WindowFrameCount(fps, window_seconds, frames.size());
  const std::size_t begin = std::max(
      frames.size() > window ? frames.size() - window : 0,
      std::min(entry_index, frames.size() - 1));
  return SelectNearestPoseInRange(current, frames, begin, frames.size());
}

}  // namespace g1_motion
