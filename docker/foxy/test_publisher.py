#!/usr/bin/env python3
import time

import rclpy
from std_msgs.msg import String


def main():
    rclpy.init()
    node = rclpy.create_node("local_foxy_test_publisher")
    publisher = node.create_publisher(String, "/unitree_test", 10)
    message = String()
    message.data = "local-foxy-to-g1-ok"

    for _ in range(40):
        publisher.publish(message)
        rclpy.spin_once(node, timeout_sec=0.05)
        time.sleep(0.15)

    node.destroy_node()
    rclpy.shutdown()
    print("published-40")


if __name__ == "__main__":
    main()
