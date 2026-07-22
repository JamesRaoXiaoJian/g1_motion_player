#!/usr/bin/env python3
import argparse
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from unitree_hg.msg import LowState


WAIST_JOINTS = {
    "waist_yaw": 12,
    "waist_roll": 13,
    "waist_pitch": 14,
}

ARM_5DOF_JOINTS = {
    "left_shoulder_pitch": 15,
    "left_shoulder_roll": 16,
    "left_shoulder_yaw": 17,
    "left_elbow_pitch": 18,
    "left_elbow_roll": 19,
    "right_shoulder_pitch": 22,
    "right_shoulder_roll": 23,
    "right_shoulder_yaw": 24,
    "right_elbow_pitch": 25,
    "right_elbow_roll": 26,
}

ARM_7DOF_JOINTS = {
    "left_shoulder_pitch": 15,
    "left_shoulder_roll": 16,
    "left_shoulder_yaw": 17,
    "left_elbow": 18,
    "left_wrist_roll": 19,
    "left_wrist_pitch": 20,
    "left_wrist_yaw": 21,
    "right_shoulder_pitch": 22,
    "right_shoulder_roll": 23,
    "right_shoulder_yaw": 24,
    "right_elbow": 25,
    "right_wrist_roll": 26,
    "right_wrist_pitch": 27,
    "right_wrist_yaw": 28,
}


class UpperBodyReader(Node):
    def __init__(self, joints, print_rate):
        super().__init__("g1_upper_body_reader")
        self.joints = joints
        self.print_period = 1.0 / print_rate
        self.last_print_time = 0.0
        self.subscription = self.create_subscription(
            LowState,
            "/lowstate",
            self.on_low_state,
            qos_profile_sensor_data,
        )

    def on_low_state(self, message):
        now = time.monotonic()
        if now - self.last_print_time < self.print_period:
            return
        self.last_print_time = now

        values = [
            f"{name}={message.motor_state[index].q:.6f}"
            for name, index in self.joints.items()
        ]
        print(" ".join(values), flush=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Read G1 upper-body joint angles from /lowstate."
    )
    parser.add_argument("--arm-dof", type=int, choices=(5, 7), default=7)
    parser.add_argument("--rate", type=float, default=10.0, help="Print rate in Hz")
    parser.add_argument("--include-waist", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.rate <= 0:
        raise SystemExit("--rate must be greater than zero")

    arm_joints = ARM_5DOF_JOINTS if args.arm_dof == 5 else ARM_7DOF_JOINTS
    joints = dict(WAIST_JOINTS) if args.include_waist else {}
    joints.update(arm_joints)

    rclpy.init()
    node = UpperBodyReader(joints, args.rate)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
