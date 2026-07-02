#include <array>
#include <cmath>
#include <iostream>
#include <vector>

#include "src/replay_planner.hpp"

namespace {

struct Frame {
    std::array<float, 29> joints{};
};

constexpr std::array<int, 17> kArmJoints = {
    15, 16, 17, 18, 19, 20, 21,
    22, 23, 24, 25, 26, 27, 28,
    12, 13, 14,
};

Frame MakeFrame(float value) {
    Frame frame;
    for (int joint : kArmJoints) {
        frame.joints[joint] = value;
    }
    return frame;
}

int ExpectEqual(const char* name, std::size_t actual, std::size_t expected) {
    if (actual == expected) {
        return 0;
    }
    std::cerr << name << ": expected " << expected << ", got " << actual << std::endl;
    return 1;
}

}  // namespace

int main() {
    replay_planner::ControlledPose current{};

    {
        std::vector<Frame> frames = {
            MakeFrame(8.0f),
            MakeFrame(3.0f),
            MakeFrame(1.0f),
            MakeFrame(0.2f),
            MakeFrame(0.01f),
        };
        std::size_t entry = replay_planner::SelectNearestEntryIndex(
            current,
            frames,
            kArmJoints,
            2.0f,
            2.0f
        );
        if (int error = ExpectEqual("entry stays inside the leading window", entry, 3)) {
            return error;
        }
    }

    {
        std::vector<Frame> frames = {
            MakeFrame(0.01f),
            MakeFrame(0.02f),
            MakeFrame(5.0f),
            MakeFrame(2.0f),
            MakeFrame(0.5f),
            MakeFrame(0.1f),
        };
        std::size_t exit = replay_planner::SelectNearestExitIndex(
            current,
            frames,
            kArmJoints,
            2.0f,
            2.0f,
            3
        );
        if (int error = ExpectEqual("exit searches the trailing window after entry", exit, 5)) {
            return error;
        }
    }

    return 0;
}
