#include "core/motion_core.hpp"

#include <rclcpp/rclcpp.hpp>
#include <unitree_hg/msg/low_cmd.hpp>
#include <unitree_hg/msg/low_state.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>

using namespace std::chrono_literals;

namespace {

using Clock = std::chrono::steady_clock;

constexpr auto kStateTimeout = 500ms;
constexpr auto kPublisherCheckPeriod = 1s;
constexpr auto kArrivalTimeout = 5s;
constexpr float kArmTrackingLimit = 0.35F;
constexpr float kWaistTrackingLimit = 0.20F;
constexpr float kArmArrivalTolerance = 0.08F;
constexpr float kWaistArrivalTolerance = 0.05F;
constexpr int kTrackingViolationCycles = 15;
constexpr int kArrivalStableCycles = 10;
constexpr int kLateCycleLimit = 3;

std::atomic<bool> g_stop_requested{false};

void HandleSignal(int) { g_stop_requested.store(true); }

struct TrackingError {
  float arm{0.0F};
  float waist{0.0F};
};

class PeriodicSchedule {
 public:
  explicit PeriodicSchedule(float fps)
      : period_(std::chrono::duration_cast<Clock::duration>(
            std::chrono::duration<double>(1.0 / fps))),
        next_(Clock::now() + period_) {}

  void Wait() {
    const auto now = Clock::now();
    if (now > next_ + period_ * 2) {
      ++late_cycles_;
    } else {
      late_cycles_ = 0;
    }
    if (late_cycles_ >= kLateCycleLimit) {
      throw std::runtime_error("control loop missed more than two periods for three cycles");
    }
    if (now < next_) {
      std::this_thread::sleep_until(next_);
    }
    next_ += period_;
  }

 private:
  Clock::duration period_;
  Clock::time_point next_;
  int late_cycles_{0};
};

class G1RosTransport : public rclcpp::Node {
 public:
  G1RosTransport() : Node("g1_csv_replay") {
    auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    publisher_ = create_publisher<unitree_hg::msg::LowCmd>("/arm_sdk", qos);
    subscription_ = create_subscription<unitree_hg::msg::LowState>(
        "/lowstate", qos, [this](unitree_hg::msg::LowState::SharedPtr message) {
          for (std::size_t i = 0; i < pose_.size(); ++i) {
            pose_[i] = message->motor_state[g1_motion::kMotorIndices[i]].q;
          }
          last_state_time_ = Clock::now();
          state_received_ = true;
        });
  }

  bool WaitForState(std::chrono::seconds timeout) {
    const auto deadline = Clock::now() + timeout;
    while (!g_stop_requested.load() && !state_received_ && Clock::now() < deadline) {
      rclcpp::spin_some(shared_from_this());
      std::this_thread::sleep_for(10ms);
    }
    return state_received_;
  }

  void Pump() { rclcpp::spin_some(shared_from_this()); }

  void CheckRuntime(const g1_motion::ControlledPose &commanded,
                    bool check_tracking) {
    Pump();
    if (g_stop_requested.load()) {
      throw std::runtime_error("stop requested");
    }
    if (!state_received_ || Clock::now() - last_state_time_ > kStateTimeout) {
      throw std::runtime_error("/lowstate timeout");
    }

    const auto now = Clock::now();
    if (now >= next_publisher_check_) {
      const auto publishers = count_publishers("/arm_sdk");
      if (publishers > 1) {
        throw std::runtime_error("multiple /arm_sdk publishers detected: " +
                                 std::to_string(publishers));
      }
      next_publisher_check_ = now + kPublisherCheckPeriod;
    }

    if (!check_tracking) {
      tracking_violation_cycles_ = 0;
      return;
    }
    const auto error = ErrorFrom(commanded);
    if (error.arm > kArmTrackingLimit || error.waist > kWaistTrackingLimit) {
      ++tracking_violation_cycles_;
    } else {
      tracking_violation_cycles_ = 0;
    }
    if (tracking_violation_cycles_ >= kTrackingViolationCycles) {
      throw std::runtime_error(
          "tracking error persisted: arm=" + std::to_string(error.arm) +
          " rad, waist=" + std::to_string(error.waist) + " rad");
    }
  }

  g1_motion::ControlledPose pose() const { return pose_; }

  TrackingError ErrorFrom(const g1_motion::ControlledPose &target) const {
    TrackingError result;
    for (std::size_t i = 0; i < target.size(); ++i) {
      const float error = std::abs(pose_[i] - target[i]);
      if (i < 14) {
        result.arm = std::max(result.arm, error);
      } else {
        result.waist = std::max(result.waist, error);
      }
    }
    return result;
  }

  void Send(const g1_motion::ControlledPose &pose, float weight) {
    unitree_hg::msg::LowCmd command;
    for (std::size_t i = 0; i < pose.size(); ++i) {
      auto &motor = command.motor_cmd[g1_motion::kMotorIndices[i]];
      motor.q = pose[i];
      motor.dq = 0.0F;
      motor.tau = 0.0F;
      motor.kp = i < 14 ? 60.0F : (i == 14 ? 80.0F : 50.0F);
      motor.kd = i < 14 ? 1.5F : (i == 14 ? 2.0F : 1.5F);
    }
    command.motor_cmd[29].q = std::clamp(weight, 0.0F, 1.0F);
    publisher_->publish(command);
  }

 private:
  rclcpp::Publisher<unitree_hg::msg::LowCmd>::SharedPtr publisher_;
  rclcpp::Subscription<unitree_hg::msg::LowState>::SharedPtr subscription_;
  g1_motion::ControlledPose pose_{};
  Clock::time_point last_state_time_{};
  Clock::time_point next_publisher_check_{};
  bool state_received_{false};
  int tracking_violation_cycles_{0};
};

void BestEffortRampDown(const std::shared_ptr<G1RosTransport> &node,
                        const g1_motion::ControlledPose &hold,
                        float start_weight, float fps) noexcept {
  if (!node || start_weight <= 0.0F) {
    return;
  }
  try {
    const int steps = std::max(1, static_cast<int>(fps * 2.0F));
    const auto period = std::chrono::duration_cast<Clock::duration>(
        std::chrono::duration<double>(1.0 / fps));
    auto next = Clock::now();
    for (int step = steps; step >= 0; --step) {
      node->Pump();
      node->Send(hold, start_weight * static_cast<float>(step) /
                           static_cast<float>(steps));
      next += period;
      std::this_thread::sleep_until(next);
    }
  } catch (...) {
    // This is the final safety path; no exception may bypass shutdown.
  }
}

void WaitForActualPose(const std::shared_ptr<G1RosTransport> &node,
                       const g1_motion::ControlledPose &target,
                       PeriodicSchedule &schedule) {
  const auto deadline = Clock::now() + kArrivalTimeout;
  int stable_cycles = 0;
  while (Clock::now() < deadline) {
    node->CheckRuntime(target, true);
    node->Send(target, 1.0F);
    const auto error = node->ErrorFrom(target);
    if (error.arm <= kArmArrivalTolerance &&
        error.waist <= kWaistArrivalTolerance) {
      ++stable_cycles;
      if (stable_cycles >= kArrivalStableCycles) {
        return;
      }
    } else {
      stable_cycles = 0;
    }
    schedule.Wait();
  }
  const auto error = node->ErrorFrom(target);
  throw std::runtime_error("actual pose did not settle: arm=" +
                           std::to_string(error.arm) + " rad, waist=" +
                           std::to_string(error.waist) + " rad");
}

}  // namespace

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  std::signal(SIGINT, HandleSignal);
  std::signal(SIGTERM, HandleSignal);

  std::shared_ptr<G1RosTransport> node;
  g1_motion::ControlledPose current{};
  float current_weight = 0.0F;
  float fps = 50.0F;
  bool control_started = false;

  try {
    if (argc < 2) {
      throw std::invalid_argument(
          "usage: ros2 run g1_motion_player_ros2 csv_replay_ros2 "
          "<csv> [--execute] [--fps N]");
    }

    const std::string csv_path = argv[1];
    bool execute = false;
    for (int i = 2; i < argc; ++i) {
      const std::string argument = argv[i];
      if (argument == "--execute") {
        execute = true;
      } else if (argument == "--fps" && i + 1 < argc) {
        fps = std::stof(argv[++i]);
      } else {
        throw std::invalid_argument("unknown or incomplete argument: " + argument);
      }
    }
    if (!(fps > 0.0F && fps <= 500.0F) || !std::isfinite(fps)) {
      throw std::invalid_argument("fps must be finite and in (0, 500]");
    }

    const auto frames = g1_motion::LoadCsv(csv_path);
    std::cout << "validated " << frames.size() << " frames at " << fps << " Hz\n";
    if (!execute) {
      std::cout << "validation only; add --execute to control the robot\n";
      rclcpp::shutdown();
      return 0;
    }

    node = std::make_shared<G1RosTransport>();
    if (!node->WaitForState(5s)) {
      throw std::runtime_error("no /lowstate received within 5 seconds");
    }
    current = node->pose();
    node->CheckRuntime(current, false);

    const auto initial = current;
    const std::size_t entry =
        g1_motion::SelectNearestEntryIndex(initial, frames, fps, 2.0F);
    const std::size_t exit =
        g1_motion::SelectNearestExitIndex(initial, frames, fps, 2.0F, entry);
    const float dt = 1.0F / fps;

    std::cerr << "CONTROL STARTS IN 3 SECONDS. Keep emergency stop ready.\n";
    const auto start_time = Clock::now() + 3s;
    while (Clock::now() < start_time) {
      node->CheckRuntime(current, false);
      std::this_thread::sleep_for(20ms);
    }

    PeriodicSchedule schedule(fps);
    control_started = true;
    for (int step = 0; step <= static_cast<int>(fps); ++step) {
      node->CheckRuntime(current, false);
      current_weight = static_cast<float>(step) / fps;
      node->Send(current, current_weight);
      schedule.Wait();
    }

    while (!g1_motion::PoseReached(current, frames[entry])) {
      current = g1_motion::ClampVelocity(current, frames[entry], 0.5F, dt);
      node->CheckRuntime(current, true);
      node->Send(current, 1.0F);
      current_weight = 1.0F;
      schedule.Wait();
    }
    WaitForActualPose(node, frames[entry], schedule);

    for (std::size_t i = entry; i <= exit; ++i) {
      current = g1_motion::ClampVelocity(current, frames[i], 0.8F, dt);
      node->CheckRuntime(current, true);
      node->Send(current, 1.0F);
      schedule.Wait();
    }

    while (!g1_motion::PoseReached(current, initial)) {
      current = g1_motion::ClampVelocity(current, initial, 0.5F, dt);
      node->CheckRuntime(current, true);
      node->Send(current, 1.0F);
      schedule.Wait();
    }
    WaitForActualPose(node, initial, schedule);

    BestEffortRampDown(node, current, 1.0F, fps);
    current_weight = 0.0F;
    control_started = false;
    rclcpp::shutdown();
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "SAFETY STOP: " << error.what() << '\n';
    if (control_started) {
      std::cerr << "ramping /arm_sdk weight down to zero\n";
      BestEffortRampDown(node, current, current_weight, fps);
    }
    rclcpp::shutdown();
    return 1;
  }
}
