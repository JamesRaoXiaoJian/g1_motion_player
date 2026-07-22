#include "core/motion_core.hpp"

#include <rclcpp/rclcpp.hpp>
#include <unitree_hg/msg/low_cmd.hpp>
#include <unitree_hg/msg/low_state.hpp>

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string>
#include <thread>

using namespace std::chrono_literals;

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
          state_received_ = true;
        });
  }

  bool WaitForState(std::chrono::seconds timeout) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (rclcpp::ok() && !state_received_ && std::chrono::steady_clock::now() < deadline) {
      rclcpp::spin_some(shared_from_this());
      std::this_thread::sleep_for(10ms);
    }
    return state_received_;
  }

  g1_motion::ControlledPose pose() const { return pose_; }

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
  bool state_received_{false};
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  if (argc < 2) {
    std::cerr << "usage: ros2 run g1_motion_player_ros2 csv_replay_ros2 "
                 "<csv> [--execute] [--fps N]\n";
    rclcpp::shutdown();
    return 2;
  }

  try {
    std::string csv_path = argv[1];
    bool execute = false;
    float fps = 50.0F;
    for (int i = 2; i < argc; ++i) {
      const std::string argument = argv[i];
      if (argument == "--execute") execute = true;
      else if (argument == "--fps" && i + 1 < argc) fps = std::stof(argv[++i]);
      else throw std::invalid_argument("unknown or incomplete argument: " + argument);
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

    auto node = std::make_shared<G1RosTransport>();
    if (!node->WaitForState(5s)) {
      throw std::runtime_error("no /lowstate received within 5 seconds");
    }
    const auto initial = node->pose();
    const std::size_t entry =
        g1_motion::SelectNearestEntryIndex(initial, frames, fps, 2.0F);
    const std::size_t exit =
        g1_motion::SelectNearestExitIndex(initial, frames, fps, 2.0F, entry);
    const auto period = std::chrono::duration<double>(1.0 / fps);
    const float dt = 1.0F / fps;
    auto current = initial;

    std::cerr << "CONTROL STARTS IN 3 SECONDS. Keep emergency stop ready.\n";
    std::this_thread::sleep_for(3s);
    for (int step = 0; rclcpp::ok() && step <= static_cast<int>(fps); ++step) {
      node->Send(current, static_cast<float>(step) / fps);
      std::this_thread::sleep_for(period);
    }
    while (rclcpp::ok() && !g1_motion::PoseReached(current, frames[entry])) {
      current = g1_motion::ClampVelocity(current, frames[entry], 0.5F, dt);
      node->Send(current, 1.0F);
      std::this_thread::sleep_for(period);
    }
    for (std::size_t i = entry; rclcpp::ok() && i <= exit; ++i) {
      current = g1_motion::ClampVelocity(current, frames[i], 0.8F, dt);
      node->Send(current, 1.0F);
      std::this_thread::sleep_for(period);
    }
    while (rclcpp::ok() && !g1_motion::PoseReached(current, initial)) {
      current = g1_motion::ClampVelocity(current, initial, 0.5F, dt);
      node->Send(current, 1.0F);
      std::this_thread::sleep_for(period);
    }
    for (int step = static_cast<int>(fps * 2); step >= 0; --step) {
      node->Send(current, static_cast<float>(step) / (fps * 2.0F));
      std::this_thread::sleep_for(period);
    }
    rclcpp::shutdown();
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "error: " << error.what() << '\n';
    rclcpp::shutdown();
    return 1;
  }
}
