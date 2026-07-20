// G1 Full-Body CSV Motion Replay — Debug Mode
// Publishes directly to rt/user_lowcmd for direct motor control.
// Requires robot to be in debug mode (motion controller OFF) already.
// Use remote control L2+A to enter PASSIVE/debug mode before running.
//
// Usage: ./csv_replay_debug <csv> [fps] [net]
//        ./csv_replay_debug <net> <csv> [fps]  (backward compatible)
//        default net is eth0

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <unitree/idl/hg/LowCmd_.hpp>
#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/channel/channel_publisher.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>

static const std::string kTopicUserCtrl = "rt/user_lowcmd";
static const std::string kTopicState = "rt/lowstate";

// Joint indices for G1 (29 DOF)
enum JointIndex {
    kLeftHipPitch, kLeftHipRoll, kLeftHipYaw, kLeftKnee, kLeftAnkle, kLeftAnkleRoll,
    kRightHipPitch, kRightHipRoll, kRightHipYaw, kRightKnee, kRightAnkle, kRightAnkleRoll,
    kWaistYaw, kWaistRoll, kWaistPitch,
    kLeftShoulderPitch, kLeftShoulderRoll, kLeftShoulderYaw, kLeftElbow,
    kLeftWristRoll, kLeftWristPitch, kLeftWristYaw,
    kRightShoulderPitch, kRightShoulderRoll, kRightShoulderYaw, kRightElbow,
    kRightWristRoll, kRightWristPitch, kRightWristYaw,
    kNotUsedJoint, kNotUsedJoint1, kNotUsedJoint2, kNotUsedJoint3, kNotUsedJoint4, kNotUsedJoint5
};

// Upper-body joint indices (arms + waist = 17 DOF)
static const std::array<int, 17> kArmJoints = {
    15, 16, 17, 18, 19, 20, 21,
    22, 23, 24, 25, 26, 27, 28,
    12, 13, 14,
};

// Leg joint indices (12 DOF)
static const std::array<int, 12> kLegJoints = {
    0, 1, 2, 3, 4, 5,
    6, 7, 8, 9, 10, 11,
};

// PD gains
static constexpr float kKp = 60.0f;
static constexpr float kKd = 1.5f;

// Velocity limits
static constexpr float kTransitionMaxVel = 0.5f;
static constexpr float kReplayMaxVel = 0.8f;
static constexpr float kDefaultFps = 50.0f;

static std::atomic<bool> g_running{true};

void SignalHandler(int) { g_running = false; }

struct CsvFrame {
    std::array<float, 29> joints;
};

bool IsHeaderRow(const std::string& line) {
    static const std::array<std::string, 36> kExpectedHeader = {
        "root_pos_x", "root_pos_y", "root_pos_z", "root_quat_x", "root_quat_y",
        "root_quat_z", "root_quat_w", "left_hip_pitch_joint",
        "left_hip_roll_joint", "left_hip_yaw_joint", "left_knee_joint", "left_ankle_joint",
        "left_ankle_roll_joint", "right_hip_pitch_joint", "right_hip_roll_joint",
        "right_hip_yaw_joint", "right_knee_joint", "right_ankle_joint", "right_ankle_roll_joint",
        "waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint",
        "left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint",
        "left_elbow_joint", "left_wrist_roll_joint", "left_wrist_pitch_joint",
        "left_wrist_yaw_joint", "right_shoulder_pitch_joint", "right_shoulder_roll_joint",
        "right_shoulder_yaw_joint", "right_elbow_joint", "right_wrist_roll_joint",
        "right_wrist_pitch_joint", "right_wrist_yaw_joint"
    };
    const std::string kUtf8Bom = "\xEF\xBB\xBF";

    std::vector<std::string> cells;
    std::stringstream ss(line);
    std::string cell;
    while (std::getline(ss, cell, ',')) {
        cells.push_back(cell);
    }
    if (cells.size() != kExpectedHeader.size()) {
        return false;
    }

    for (std::size_t i = 0; i < cells.size(); ++i) {
        if (i == 0 && cells[i].rfind(kUtf8Bom, 0) == 0) {
            cells[i] = cells[i].substr(kUtf8Bom.size());
        }
        if (cells[i] != kExpectedHeader[i]) {
            return false;
        }
    }
    return true;
}

bool ParseFps(const std::string& value, float& fps) {
    try {
        std::size_t parsed = 0;
        fps = std::stof(value, &parsed);
        if (parsed != value.size()) {
            return false;
        }
    } catch (...) {
        return false;
    }
    return std::isfinite(fps) && fps > 0.0f && fps <= 240.0f;
}

bool ParseCsvLine(
    const std::string& line,
    const std::string& csv_path,
    std::size_t line_number,
    CsvFrame& frame
) {
    std::vector<float> vals;
    std::stringstream ss(line);
    std::string cell;
    while (std::getline(ss, cell, ',')) {
        try {
            float value = std::stof(cell);
            if (!std::isfinite(value)) {
                std::cerr << "ERROR: Non-finite value at " << csv_path << ":" << line_number << std::endl;
                return false;
            }
            vals.push_back(value);
        } catch (...) {
            std::cerr << "ERROR: Invalid numeric value at " << csv_path << ":" << line_number << std::endl;
            return false;
        }
    }

    if (vals.size() != 36) {
        std::cerr << "ERROR: Each frame must contain exactly 36 columns, got " << vals.size()
                  << " at " << csv_path << ":" << line_number << std::endl;
        return false;
    }

    for (int i = 0; i < 29; i++) {
        frame.joints[i] = vals[7 + i];
    }
    return true;
}

std::vector<CsvFrame> LoadCsv(const std::string& path, float fps) {
    std::vector<CsvFrame> frames;
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "ERROR: Cannot open " << path << std::endl;
        return frames;
    }
    std::string line;
    std::size_t line_number = 0;
    while (std::getline(file, line)) {
        ++line_number;
        if (line.empty()) continue;
        if (IsHeaderRow(line)) {
            continue;
        }
        CsvFrame f;
        if (!ParseCsvLine(line, path, line_number, f)) {
            return {};
        }
        frames.push_back(f);
    }
    std::cout << "Loaded " << frames.size() << " frames ("
              << frames.size() / fps << "s @ " << fps << "fps)" << std::endl;
    return frames;
}

int main(int argc, char const* argv[]) {
    auto is_csv_path = [](const std::string& s) {
        return s.size() >= 4 && s.substr(s.size() - 4) == ".csv";
    };

    if (argc < 2) {
        std::cout << "Usage: " << argv[0] << " <csv> [fps] [net]" << std::endl;
        std::cout << "   or: " << argv[0] << " <net> <csv> [fps]" << std::endl;
        std::cout << "Default net: eth0" << std::endl;
        std::cout << std::endl;
        std::cout << "Prerequisites:" << std::endl;
        std::cout << "  Robot must be in debug mode (motion controller OFF)." << std::endl;
        std::cout << "  Use remote: L2+A to enter PASSIVE mode first." << std::endl;
        return 1;
    }

    std::string net = "eth0";
    std::string csv_path;
    float fps = kDefaultFps;

    if (is_csv_path(argv[1])) {
        csv_path = argv[1];
        if (argc >= 3) {
            if (ParseFps(argv[2], fps)) {
                if (argc >= 4) net = argv[3];
            } else {
                net = argv[2];
            }
        }
    } else {
        if (argc < 3 || !is_csv_path(argv[2])) {
            std::cout << "Usage: " << argv[0] << " <csv> [fps] [net]" << std::endl;
            return 1;
        }
        net = argv[1];
        csv_path = argv[2];
        if (argc >= 4) {
            if (!ParseFps(argv[3], fps)) {
                std::cerr << "ERROR: invalid fps value: " << argv[3] << std::endl;
                return 1;
            }
        }
    }

    auto frames = LoadCsv(csv_path, fps);
    if (frames.empty()) return 1;

    std::signal(SIGINT, SignalHandler);
    std::signal(SIGTERM, SignalHandler);

    // DDS init
    std::cout << "[INIT] Connecting via " << net << "..." << std::endl;
    unitree::robot::ChannelFactory::Instance()->Init(0, net);

    // Publisher: rt/user_lowcmd (direct motor control)
    auto user_pub = std::make_shared<unitree::robot::ChannelPublisher<unitree_hg::msg::dds_::LowCmd_>>(kTopicUserCtrl);
    user_pub->InitChannel();

    // Subscriber: rt/lowstate
    unitree_hg::msg::dds_::LowState_ state_msg;
    std::atomic<bool> state_ok{false};
    std::mutex state_mutex;
    auto state_sub = std::make_shared<unitree::robot::ChannelSubscriber<unitree_hg::msg::dds_::LowState_>>(kTopicState);
    state_sub->InitChannel([&](const void* msg) {
        std::lock_guard<std::mutex> lk(state_mutex);
        memcpy(&state_msg, msg, sizeof(unitree_hg::msg::dds_::LowState_));
        state_ok = true;
    }, 1);

    auto t0 = std::chrono::steady_clock::now();
    while (!state_ok) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if (std::chrono::duration<float>(std::chrono::steady_clock::now() - t0).count() > 5.0f) {
            std::cerr << "ERROR: No state after 5s. Is robot powered on?" << std::endl;
            return 1;
        }
    }
    std::cout << "[INIT] DDS connected." << std::endl;

    // Read current joint positions
    std::array<float, 29> cur{};
    {
        std::lock_guard<std::mutex> lk(state_mutex);
        for (int i = 0; i < 29; i++) cur[i] = state_msg.motor_state().at(i).q();
    }
    std::cout << "[JOINTS] Current positions: ";
    for (int i = 0; i < 29; i++) std::cout << std::fixed << std::setprecision(3) << cur[i] << " ";
    std::cout << std::endl;

    // Record leg initial position
    std::array<float, 12> leg_init{};
    for (int i = 0; i < 12; i++) leg_init[i] = cur[kLegJoints[i]];

    // Prepare command message
    unitree_hg::msg::dds_::LowCmd_ cmd;
    float dt = 1.0f / fps;
    float transition_max_delta = kTransitionMaxVel / fps;
    float replay_max_delta = kReplayMaxVel / fps;
    auto sleep_us = std::chrono::microseconds(static_cast<int>(dt * 1000000));

    // send: control all 29 joints
    std::array<float, 29> cmd_pos = cur;
    auto send = [&](const std::array<float, 29>& pos) {
        for (int j = 0; j < 29; j++) {
            cmd.motor_cmd().at(j).q(pos[j]);
            cmd.motor_cmd().at(j).dq(0);
            cmd.motor_cmd().at(j).kp(kKp);
            cmd.motor_cmd().at(j).kd(kKd);
            cmd.motor_cmd().at(j).tau(0);
        }
        user_pub->Write(cmd);
    };

    // Monitor thread
    std::array<float, 29> csv_target{};
    std::mutex target_mutex;
    std::atomic<bool> monitor_running{true};

    auto monitor = std::thread([&]() {
        using namespace std::chrono_literals;
        int count = 0;
        while (monitor_running.load() && g_running) {
            std::array<float, 29> state_pos{};
            {
                std::lock_guard<std::mutex> lk(state_mutex);
                for (int i = 0; i < 29; i++) state_pos[i] = state_msg.motor_state().at(i).q();
            }
            std::array<float, 29> target_copy{};
            {
                std::lock_guard<std::mutex> lk(target_mutex);
                target_copy = csv_target;
            }

            float arm_max = 0.0f;
            int arm_worst = -1;
            for (int i = 0; i < 17; i++) {
                float d = std::abs(state_pos[kArmJoints[i]] - target_copy[kArmJoints[i]]);
                if (d > arm_max) { arm_max = d; arm_worst = kArmJoints[i]; }
            }
            float leg_max = 0.0f;
            int leg_worst = -1;
            for (int i = 0; i < 12; i++) {
                float d = std::abs(state_pos[kLegJoints[i]] - leg_init[i]);
                if (d > leg_max) { leg_max = d; leg_worst = kLegJoints[i]; }
            }

            if (arm_max > 0.1f || leg_max > 0.05f || count % 10 == 0) {
                std::cout << "[MON] arm_err=" << std::fixed << std::setprecision(3) << arm_max
                          << " j=" << arm_worst
                          << " | leg_err=" << leg_max
                          << " j=" << leg_worst << std::endl;
            }
            count++;
            std::this_thread::sleep_for(200ms);
        }
    });

    // Phase 1: Transition to first frame
    if (g_running) {
        std::cout << "[REPLAY] Transitioning to first frame..." << std::endl;
        std::array<float, 29> target{};
        for (int i = 0; i < 29; i++) target[i] = frames[0].joints[i];
        for (int i = 0; i < 12; i++) target[kLegJoints[i]] = leg_init[i];

        int steps = std::max(1, static_cast<int>(2.0f / dt));
        for (int i = 0; i < steps && g_running; i++) {
            for (int j = 0; j < 29; j++) {
                float d = std::clamp(target[j] - cmd_pos[j], -transition_max_delta, transition_max_delta);
                cmd_pos[j] += d;
            }
            {
                std::lock_guard<std::mutex> lk(target_mutex);
                csv_target = target;
            }
            send(cmd_pos);
            std::this_thread::sleep_for(sleep_us);
        }
    }

    // Phase 2: Replay
    if (g_running) {
        std::cout << "[REPLAY] Playing " << frames.size() << " frames (vel=" << kReplayMaxVel << " rad/s)..." << std::endl;
        auto start = std::chrono::steady_clock::now();
        for (size_t fi = 0; fi < frames.size() && g_running; fi++) {
            auto fs = std::chrono::steady_clock::now();

            std::array<float, 29> frame_target{};
            for (int j = 0; j < 29; j++) frame_target[j] = frames[fi].joints[j];
            for (int i = 0; i < 12; i++) frame_target[kLegJoints[i]] = leg_init[i];

            for (int j = 0; j < 29; j++) {
                float d = std::clamp(frame_target[j] - cmd_pos[j], -replay_max_delta, replay_max_delta);
                cmd_pos[j] += d;
            }

            {
                std::lock_guard<std::mutex> lk(target_mutex);
                csv_target = frame_target;
            }
            send(cmd_pos);

            if (fi % std::max<int>(1, static_cast<int>(std::round(fps))) == 0) {
                float t = std::chrono::duration<float>(std::chrono::steady_clock::now() - start).count();
                std::cout << "  " << fi << "/" << frames.size() << " t=" << std::fixed << std::setprecision(1) << t << "s" << std::endl;
            }
            auto el = std::chrono::steady_clock::now() - fs;
            if (el < sleep_us) std::this_thread::sleep_for(sleep_us - el);
        }
        float total = std::chrono::duration<float>(std::chrono::steady_clock::now() - start).count();
        std::cout << "[REPLAY] Done: " << frames.size() << " frames in " << std::fixed << std::setprecision(2) << total << "s" << std::endl;
    }

    // Phase 3: Return to initial posture
    if (g_running) {
        std::cout << "[REPLAY] Returning to initial posture..." << std::endl;
        int steps = std::max(1, static_cast<int>(2.0f / dt));
        for (int i = 0; i < steps && g_running; i++) {
            for (int j = 0; j < 29; j++) {
                float d = std::clamp(cur[j] - cmd_pos[j], -transition_max_delta, transition_max_delta);
                cmd_pos[j] += d;
            }
            {
                std::lock_guard<std::mutex> lk(target_mutex);
                csv_target = cur;
            }
            send(cmd_pos);
            std::this_thread::sleep_for(sleep_us);
        }
    }

    // Cleanup
    monitor_running = false;
    if (monitor.joinable()) monitor.join();

    std::cout << "[DONE] Exit. Robot motors will hold last position." << std::endl;
    std::cout << "       Use remote control to switch back to walk mode." << std::endl;
    return 0;
}
