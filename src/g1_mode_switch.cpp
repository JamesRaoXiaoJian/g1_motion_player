// G1 FSM Mode Switch Utility
// Switch robot between different FSM states via LocoClient RPC.
//
// Usage: ./g1_mode_switch <mode> [net]
//   mode: walk | passive | standup | squat | sit | zerotorque | damp
//   Default net: eno0

#include <iostream>
#include <string>
#include <thread>
#include <chrono>

#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/loco/g1_loco_client.hpp>

const char* FsmName(int id) {
    switch (id) {
        case 0:   return "ZeroTorque";
        case 1:   return "PASSIVE(Damp)";
        case 2:   return "Squat";
        case 3:   return "Sit";
        case 4:   return "StandUp";
        case 500: return "WalkRun";
        case 501: return "WalkRunExpert";
        case 801: return "ArmAction/Expert";
        default:  return "Unknown";
    }
}

int main(int argc, char const* argv[]) {
    if (argc < 2) {
        std::cout << "Usage: " << argv[0] << " <mode> [net]" << std::endl;
        std::cout << "Modes:" << std::endl;
        std::cout << "  walk       - Switch to WalkRun (FSM=500)" << std::endl;
        std::cout << "  passive    - Switch to PASSIVE/Damp (FSM=1)" << std::endl;
        std::cout << "  standup    - Stand up (FSM=4)" << std::endl;
        std::cout << "  squat      - Squat (FSM=2)" << std::endl;
        std::cout << "  sit        - Sit (FSM=3)" << std::endl;
        std::cout << "  zerotorque - Zero torque (FSM=0)" << std::endl;
        std::cout << "  damp       - Same as passive" << std::endl;
        std::cout << "  status     - Just print current FSM" << std::endl;
        std::cout << "Default net: eno0" << std::endl;
        return 1;
    }

    std::string mode = argv[1];
    std::string net = (argc >= 3) ? argv[2] : "eno0";

    unitree::robot::ChannelFactory::Instance()->Init(0, net);

    unitree::robot::g1::LocoClient loco;
    loco.Init();
    loco.SetTimeout(10.f);

    // Get current FSM
    int fsm_id = -1;
    int ret = loco.GetFsmId(fsm_id);
    if (ret != 0) {
        std::cerr << "ERROR: GetFsmId failed (ret=" << ret << "). Sport service not responding." << std::endl;
        return 1;
    }
    std::cout << "Current FSM: " << FsmName(fsm_id) << " (ID=" << fsm_id << ")" << std::endl;

    if (mode == "status") {
        return 0;
    }

    int target_fsm = -1;
    if (mode == "walk") {
        target_fsm = 500;
        loco.Start();
    } else if (mode == "passive" || mode == "damp") {
        target_fsm = 1;
        loco.Damp();
    } else if (mode == "standup") {
        target_fsm = 4;
        loco.StandUp();
    } else if (mode == "squat") {
        target_fsm = 2;
        loco.Squat();
    } else if (mode == "sit") {
        target_fsm = 3;
        loco.Sit();
    } else if (mode == "zerotorque") {
        target_fsm = 0;
        loco.ZeroTorque();
    } else {
        std::cerr << "Unknown mode: " << mode << std::endl;
        return 1;
    }

    std::cout << "Sent command. Waiting for FSM transition..." << std::endl;

    // Wait for FSM to change
    for (int i = 0; i < 25; i++) {  // 5 seconds max
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        ret = loco.GetFsmId(fsm_id);
        if (ret == 0) {
            std::cout << "  FSM: " << FsmName(fsm_id) << " (ID=" << fsm_id << ")" << std::endl;
            if (fsm_id == target_fsm) {
                std::cout << "Done!" << std::endl;
                return 0;
            }
        }
    }

    std::cout << "Timeout waiting for FSM=" << target_fsm << ". Current: " << FsmName(fsm_id) << " (ID=" << fsm_id << ")" << std::endl;
    return 1;
}
