// G1 Upper-Body CSV Motion Replay
// Sends keyframes to robot via rt/arm_sdk with weight mechanism.
//
// Usage: ./csv_replay <csv> [fps] [net]
//        ./csv_replay <net> <csv> [fps]  (backward compatible)
//        default net is eno0

#include <algorithm>
#include <array>
#include <chrono>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <unitree/idl/hg/LowCmd_.hpp>
#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/channel/channel_publisher.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>
#include <mutex>

static const std::string kTopicArmSDK = "rt/arm_sdk";
static const std::string kTopicState = "rt/lowstate";

// Upper-body joint indices (arms + waist = 17 DOF)
static const std::array<int, 17> kArmJoints = {
    15, 16, 17, 18, 19, 20, 21,  // left arm
    22, 23, 24, 25, 26, 27, 28,  // right arm
    12, 13, 14,                   // waist
};
static constexpr int kNotUsedJoint = 29;  // Weight slot

static constexpr float kKp = 60.0f;
static constexpr float kKd = 1.5f;
static constexpr float kMaxVel = 0.5f;  // rad/s

struct CsvFrame {
    std::array<float, 29> joints;
};

std::vector<CsvFrame> LoadCsv(const std::string& path) {
    std::vector<CsvFrame> frames;
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "ERROR: Cannot open " << path << std::endl;
        return frames;
    }
    std::string line;
    while (std::getline(file, line)) {
        if (line.empty()) continue;
        std::vector<float> vals;
        std::stringstream ss(line);
        std::string cell;
        while (std::getline(ss, cell, ',')) {
            try { vals.push_back(std::stof(cell)); } catch (...) { break; }
        }
        if (vals.size() != 36) continue;
        CsvFrame f;
        for (int i = 0; i < 29; i++) f.joints[i] = vals[7 + i];
        frames.push_back(f);
    }
    std::cout << "Loaded " << frames.size() << " frames ("
              << frames.size() / 60.0f << "s)" << std::endl;
    return frames;
}

int main(int argc, char const* argv[]) {
    auto is_csv_path = [](const std::string& s) {
        return s.size() >= 4 && s.substr(s.size() - 4) == ".csv";
    };

    if (argc < 2) {
        std::cout << "Usage: " << argv[0] << " <csv> [fps] [net]" << std::endl;
        std::cout << "   or: " << argv[0] << " <net> <csv> [fps]" << std::endl;
        std::cout << "Default net: eno0" << std::endl;
        return 1;
    }

    std::string net = "eno0";
    std::string csv_path;
    float fps = 60.0f;

    // New mode: <csv> [fps] [net]
    if (is_csv_path(argv[1])) {
        csv_path = argv[1];
        if (argc >= 3) {
            try {
                fps = std::stof(argv[2]);
                if (argc >= 4) net = argv[3];
            } catch (...) {
                net = argv[2];
            }
        }
    } else {
        // Backward-compatible mode: <net> <csv> [fps]
        if (argc < 3 || !is_csv_path(argv[2])) {
            std::cout << "Usage: " << argv[0] << " <csv> [fps] [net]" << std::endl;
            std::cout << "   or: " << argv[0] << " <net> <csv> [fps]" << std::endl;
            std::cout << "Default net: eno0" << std::endl;
            return 1;
        }
        net = argv[1];
        csv_path = argv[2];
        if (argc >= 4) {
            try { fps = std::stof(argv[3]); } catch (...) {}
        }
    }

    auto frames = LoadCsv(csv_path);
    if (frames.empty()) return 1;

    // DDS init
    std::cout << "Connecting via " << net << "..." << std::endl;
    unitree::robot::ChannelFactory::Instance()->Init(0, net);

    auto arm_pub = std::make_shared<unitree::robot::ChannelPublisher<unitree_hg::msg::dds_::LowCmd_>>(kTopicArmSDK);
    arm_pub->InitChannel();

    unitree_hg::msg::dds_::LowState_ state_msg;
    std::atomic<bool> ok{false};
    std::mutex state_mutex;
    auto state_sub = std::make_shared<unitree::robot::ChannelSubscriber<unitree_hg::msg::dds_::LowState_>>(kTopicState);
    state_sub->InitChannel([&](const void* msg) {
        std::lock_guard<std::mutex> lk(state_mutex);
        memcpy(&state_msg, msg, sizeof(unitree_hg::msg::dds_::LowState_));
        ok = true;
    }, 1);

    auto t0 = std::chrono::steady_clock::now();
    while (!ok) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if (std::chrono::duration<float>(std::chrono::steady_clock::now() - t0).count() > 5.0f) {
            std::cerr << "ERROR: No state after 5s." << std::endl;
            return 1;
        }
    }
    std::cout << "Connected." << std::endl;

    // Read current positions (protected by state_mutex)
    std::array<float, 17> cur{};
    {
        std::lock_guard<std::mutex> lk(state_mutex);
        for (int i = 0; i < 17; i++) cur[i] = state_msg.motor_state().at(kArmJoints[i]).q();
    }

    unitree_hg::msg::dds_::LowCmd_ cmd;
    float dt = 1.0f / fps;
    float max_delta = kMaxVel / fps;
    auto sleep_us = std::chrono::microseconds(static_cast<int>(dt * 1000000));
    std::atomic<float> weight{0.0f};
    float dw = 0.2f * dt;

    // For asynchronous checking: remember last commanded positions and expose weight
    std::array<float, 17> last_cmd_pos{};
    std::mutex last_cmd_mutex;
    std::atomic<bool> monitor_running{true};

    // Monitor thread: periodically compare last commanded positions to actual state
    auto monitor = std::thread([&]() {
        using namespace std::chrono_literals;
        while (monitor_running.load()) {
            std::array<float, 17> state_pos{};
            {
                std::lock_guard<std::mutex> lk(state_mutex);
                for (int i = 0; i < 17; i++) state_pos[i] = state_msg.motor_state().at(kArmJoints[i]).q();
            }
            std::array<float, 17> cmd_copy{};
            {
                std::lock_guard<std::mutex> lk(last_cmd_mutex);
                cmd_copy = last_cmd_pos;
            }
            float w = weight.load();
            float max_diff = 0.0f;
            for (int i = 0; i < 17; i++) {
                float d = std::abs(state_pos[i] - cmd_copy[i]);
                if (d > max_diff) max_diff = d;
            }
            if (max_diff > 0.05f) {
                std::cout << "[DEBUG] State mismatch detected: max_delta=" << max_diff
                          << " weight=" << w << std::endl;
            } else {
                // occasional low-verbosity debug
            }
            std::this_thread::sleep_for(200ms);
        }
    });

    auto send = [&](const std::array<float, 17>& pos) {
        float w = weight.load();
        cmd.motor_cmd().at(kNotUsedJoint).q(w);
        for (int j = 0; j < 17; j++) {
            cmd.motor_cmd().at(kArmJoints[j]).q(pos[j]);
            cmd.motor_cmd().at(kArmJoints[j]).dq(0);
            cmd.motor_cmd().at(kArmJoints[j]).kp(kKp);
            cmd.motor_cmd().at(kArmJoints[j]).kd(kKd);
            cmd.motor_cmd().at(kArmJoints[j]).tau(0);
        }
        {
            std::lock_guard<std::mutex> lk(last_cmd_mutex);
            last_cmd_pos = pos;
        }
        arm_pub->Write(cmd);
    };

    // Phase 1: Engage
    std::cout << "Engaging..." << std::endl;
    for (int i = 0; i < (int)(1.0f / dt); i++) {
        weight = std::clamp(weight + dw, 0.0f, 1.0f);
        send(cur);
        std::this_thread::sleep_for(sleep_us);
    }

    // Phase 2: Transition
    std::cout << "Transitioning..." << std::endl;
    std::array<float, 17> target{};
    for (int i = 0; i < 17; i++) target[i] = frames[0].joints[kArmJoints[i]];
    std::array<float, 17> cmd_pos = cur;

    for (int i = 0; i < (int)(2.0f / dt); i++) {
        weight = std::clamp(weight.load() + dw, 0.0f, 1.0f);
        for (int j = 0; j < 17; j++) {
            float d = std::clamp(target[j] - cmd_pos[j], -max_delta, max_delta);
            cmd_pos[j] += d;
        }
        send(cmd_pos);
        std::this_thread::sleep_for(sleep_us);
    }

    // Phase 3: Replay
    std::cout << "Replaying " << frames.size() << " frames..." << std::endl;
    auto start = std::chrono::steady_clock::now();
    for (size_t fi = 0; fi < frames.size(); fi++) {
        auto fs = std::chrono::steady_clock::now();
        for (int j = 0; j < 17; j++) {
            float d = std::clamp(frames[fi].joints[kArmJoints[j]] - cmd_pos[j], -max_delta, max_delta);
            cmd_pos[j] += d;
        }
        send(cmd_pos);
        if (fi % 60 == 0) {
            float t = std::chrono::duration<float>(std::chrono::steady_clock::now() - start).count();
            std::cout << "  " << fi << "/" << frames.size() << " t=" << t << "s" << std::endl;
        }
        auto el = std::chrono::steady_clock::now() - fs;
        if (el < sleep_us) std::this_thread::sleep_for(sleep_us - el);
    }
    float total = std::chrono::duration<float>(std::chrono::steady_clock::now() - start).count();
    std::cout << "Done: " << frames.size() << " frames in " << total << "s" << std::endl;

    // Phase 4: Disengage
    std::cout << "Disengaging..." << std::endl;
    // Phase 4a: Smoothly move back to initial positions to avoid sudden "clack"
    std::cout << "Returning to initial posture..." << std::endl;
    for (int i = 0; i < (int)(2.0f / dt); i++) {
        for (int j = 0; j < 17; j++) {
            float d = std::clamp(cur[j] - cmd_pos[j], -max_delta, max_delta);
            cmd_pos[j] += d;
        }
        send(cmd_pos);
        std::this_thread::sleep_for(sleep_us);
    }

    // Phase 4b: Ramp down weight while holding safe positions
    std::cout << "Disengaging (ramp down) ..." << std::endl;
    for (int i = 0; i < (int)(2.0f / dt); i++) {
        weight = std::clamp(weight.load() - dw, 0.0f, 1.0f);
        // keep sending current cmd_pos while weight changes
        send(cmd_pos);
        std::this_thread::sleep_for(sleep_us);
    }
    weight = 0.0f;
    send(cmd_pos);

    // stop monitor thread and join
    monitor_running = false;
    if (monitor.joinable()) monitor.join();

    std::cout << "Robot returned to built-in control." << std::endl;
    return 0;
}
