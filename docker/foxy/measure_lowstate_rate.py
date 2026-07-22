#!/usr/bin/env python3
import argparse
import math
import statistics
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from unitree_hg.msg import LowState


class LowStateRateMeter(Node):
    def __init__(self, report_interval):
        super().__init__("g1_lowstate_rate_meter")
        self.report_interval = report_interval
        self.start_time = time.monotonic()
        self.window_start = self.start_time
        self.last_message_time = None
        self.total_messages = 0
        self.window_messages = 0
        self.periods = []
        self.subscription = self.create_subscription(
            LowState,
            "/lowstate",
            self.on_low_state,
            qos_profile_sensor_data,
        )
        self.timer = self.create_timer(report_interval, self.report)

    def on_low_state(self, _message):
        now = time.monotonic()
        if self.last_message_time is not None:
            self.periods.append(now - self.last_message_time)
        self.last_message_time = now
        self.total_messages += 1
        self.window_messages += 1

    def report(self):
        now = time.monotonic()
        elapsed = now - self.window_start
        rate = self.window_messages / elapsed if elapsed > 0 else 0.0
        print(
            f"window_hz={rate:.2f} messages={self.window_messages} "
            f"elapsed={elapsed:.3f}s",
            flush=True,
        )
        self.window_start = now
        self.window_messages = 0

    def summary(self):
        elapsed = time.monotonic() - self.start_time
        average_rate = self.total_messages / elapsed if elapsed > 0 else 0.0
        valid_periods = [period for period in self.periods if math.isfinite(period)]

        print("\nSummary")
        print(f"messages={self.total_messages}")
        print(f"elapsed={elapsed:.3f}s")
        print(f"average_hz={average_rate:.2f}")
        if valid_periods:
            mean_period = statistics.fmean(valid_periods)
            jitter = statistics.pstdev(valid_periods)
            print(f"mean_period_ms={mean_period * 1000.0:.3f}")
            print(f"jitter_stddev_ms={jitter * 1000.0:.3f}")
            print(f"min_period_ms={min(valid_periods) * 1000.0:.3f}")
            print(f"max_period_ms={max(valid_periods) * 1000.0:.3f}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Measure the full receive rate of G1 /lowstate."
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Measurement duration in seconds; use 0 to run until Ctrl+C",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Rate reporting interval in seconds",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.duration < 0:
        raise SystemExit("--duration must be zero or greater")
    if args.interval <= 0:
        raise SystemExit("--interval must be greater than zero")

    rclpy.init()
    node = LowStateRateMeter(args.interval)
    deadline = time.monotonic() + args.duration if args.duration else None

    try:
        while rclpy.ok() and (deadline is None or time.monotonic() < deadline):
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.summary()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
