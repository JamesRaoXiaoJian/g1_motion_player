#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <vector>

namespace replay_planner {

using ControlledPose = std::array<float, 17>;

inline float ControlledJointWeight(std::size_t index) {
    if (index >= 14) {
        return 2.0f;  // waist joints
    }
    if (index <= 2 || (index >= 7 && index <= 9)) {
        return 1.5f;  // shoulder joints
    }
    return 1.0f;
}

inline float PoseCost(const ControlledPose& current, const ControlledPose& candidate) {
    float cost = 0.0f;
    for (std::size_t i = 0; i < current.size(); ++i) {
        float diff = current[i] - candidate[i];
        cost += ControlledJointWeight(i) * diff * diff;
    }
    return cost;
}

inline std::size_t WindowFrameCount(float fps, float window_seconds, std::size_t total_frames) {
    if (total_frames == 0) {
        return 0;
    }
    if (!std::isfinite(fps) || fps <= 0.0f || !std::isfinite(window_seconds) || window_seconds <= 0.0f) {
        return total_frames;
    }
    std::size_t requested = static_cast<std::size_t>(std::ceil(fps * window_seconds));
    requested = std::max<std::size_t>(1, requested);
    return std::min(total_frames, requested);
}

template <typename Frame>
ControlledPose ExtractControlledPose(
    const Frame& frame,
    const std::array<int, 17>& controlled_joints
) {
    ControlledPose pose{};
    for (std::size_t i = 0; i < controlled_joints.size(); ++i) {
        pose[i] = frame.joints[controlled_joints[i]];
    }
    return pose;
}

template <typename Frame>
std::size_t SelectNearestIndexInRange(
    const ControlledPose& current,
    const std::vector<Frame>& frames,
    const std::array<int, 17>& controlled_joints,
    std::size_t begin,
    std::size_t end
) {
    if (frames.empty()) {
        return 0;
    }
    begin = std::min(begin, frames.size() - 1);
    end = std::min(end, frames.size());
    if (begin >= end) {
        return begin;
    }

    std::size_t best_index = begin;
    float best_cost = PoseCost(current, ExtractControlledPose(frames[begin], controlled_joints));
    for (std::size_t i = begin + 1; i < end; ++i) {
        float cost = PoseCost(current, ExtractControlledPose(frames[i], controlled_joints));
        if (cost < best_cost) {
            best_cost = cost;
            best_index = i;
        }
    }
    return best_index;
}

template <typename Frame>
std::size_t SelectNearestEntryIndex(
    const ControlledPose& current,
    const std::vector<Frame>& frames,
    const std::array<int, 17>& controlled_joints,
    float fps,
    float window_seconds
) {
    std::size_t window = WindowFrameCount(fps, window_seconds, frames.size());
    return SelectNearestIndexInRange(current, frames, controlled_joints, 0, window);
}

template <typename Frame>
std::size_t SelectNearestExitIndex(
    const ControlledPose& current,
    const std::vector<Frame>& frames,
    const std::array<int, 17>& controlled_joints,
    float fps,
    float window_seconds,
    std::size_t entry_index
) {
    if (frames.empty()) {
        return 0;
    }
    std::size_t window = WindowFrameCount(fps, window_seconds, frames.size());
    std::size_t begin = frames.size() > window ? frames.size() - window : 0;
    begin = std::max(begin, std::min(entry_index, frames.size() - 1));
    return SelectNearestIndexInRange(current, frames, controlled_joints, begin, frames.size());
}

}  // namespace replay_planner
