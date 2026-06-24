// Minimal G1 connection test
// Usage: ./test_connection <network_interface>

#include <chrono>
#include <cstring>
#include <iostream>
#include <thread>

#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cout << "Usage: " << argv[0] << " <network_interface>" << std::endl;
        return 1;
    }
    std::string net = argv[1];
    std::cout << "Connecting via " << net << "..." << std::endl;
    unitree::robot::ChannelFactory::Instance()->Init(0, net);

    unitree_hg::msg::dds_::LowState_ state;
    bool received = false;
    auto sub = std::make_shared<unitree::robot::ChannelSubscriber<unitree_hg::msg::dds_::LowState_>>("rt/lowstate");
    sub->InitChannel([&](const void* msg) {
        memcpy(&state, msg, sizeof(unitree_hg::msg::dds_::LowState_));
        received = true;
    }, 1);

    auto start = std::chrono::steady_clock::now();
    while (!received) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if (std::chrono::duration<float>(std::chrono::steady_clock::now() - start).count() > 5.0f) {
            std::cerr << "FAIL: No data after 5s." << std::endl;
            return 1;
        }
    }
    std::cout << "\n=== CONNECTED ===" << std::endl;
    for (int s = 0; s < 5; s++) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        std::cout << "  LArm: ";
        for (int i = 15; i < 22; i++) printf("%+.2f ", state.motor_state().at(i).q());
        std::cout << " RArm: ";
        for (int i = 22; i < 29; i++) printf("%+.2f ", state.motor_state().at(i).q());
        std::cout << std::endl;
    }
    std::cout << "PASSED." << std::endl;
    return 0;
}
