# Initial Pose vs Keyframe First Frame Analysis

Analysis of the G1 robot's default standing pose compared to the first frame of each
keyframe CSV, based on recorded telemetry from full motion playback sessions.

## Data Sources

| File | Rows | Duration (60fps) | Description |
|------|------|-------------------|-------------|
| `zuoyi_recorded.csv` | 1259 | 21.0s | Full playback recording (zuoyi sitting motion) |
| `wave_recorded.csv` | 1259 | 21.0s | Full playback recording (wave motion) |
| `zuoyi.csv` | 600 | 10.0s | Keyframe data (zuoyi) |
| `wave.csv` | 600 | 10.0s | Keyframe data (wave) |

Each recording spans ~21s: Engage (1s) + Transition (2s) + Replay (10s) + Disengage (4s)
+ remaining frames.

## Important: CSV Column Mapping

The CSV header names (e.g. `j_pelvis`, `j_spine1`) are **misleading**. They come from the
LAFAN1 retargeting skeleton convention and do NOT match the SDK motor ordering. The actual
mapping, as defined in `csv_replay.cpp`, is:

| CSV Col | SDK Index | SDK Joint Name | Header Name | Controlled? |
|---------|-----------|----------------|-------------|-------------|
| 7 | 0 | LeftHipPitch | j_pelvis | No (leg) |
| 8 | 1 | LeftHipRoll | j_spine1 | No (leg) |
| 9 | 2 | LeftHipYaw | j_spine2 | No (leg) |
| 10 | 3 | LeftKnee | j_spine3 | No (leg) |
| 11 | 4 | LeftAnkle | j_left_hip | No (leg) |
| 12 | 5 | LeftAnkleRoll | j_left_knee | No (leg) |
| 13 | 6 | RightHipPitch | j_left_ankle | No (leg) |
| 14 | 7 | RightHipRoll | j_right_hip | No (leg) |
| 15 | 8 | RightHipYaw | j_right_knee | No (leg) |
| 16 | 9 | RightKnee | j_right_ankle | No (leg) |
| 17 | 10 | RightAnkle | j_chest | No (leg) |
| 18 | 11 | RightAnkleRoll | j_neck | No (leg) |
| 19 | 12 | **WaistYaw** | j_head | **Yes** |
| 20 | 13 | **WaistRoll** | j_left_shoulder | **Yes** |
| 21 | 14 | **WaistPitch** | j_left_arm | **Yes** |
| 22 | 15 | **LeftShoulderPitch** | j_left_fore_arm | **Yes** |
| 23 | 16 | **LeftShoulderRoll** | j_left_hand | **Yes** |
| 24 | 17 | **LeftShoulderYaw** | j_right_shoulder | **Yes** |
| 25 | 18 | **LeftElbow** | j_right_arm | **Yes** |
| 26 | 19 | **LeftWristRoll** | j_right_fore_arm | **Yes** |
| 27 | 20 | **LeftWristPitch** | j_right_hand | **Yes** |
| 28 | 21 | **LeftWristYaw** | j_left_finger | **Yes** |
| 29 | 22 | **RightShoulderPitch** | j_right_finger | **Yes** |
| 30 | 23 | **RightShoulderRoll** | j_left_toe | **Yes** |
| 31 | 24 | **RightShoulderYaw** | j_right_toe | **Yes** |
| 32 | 25 | **RightElbow** | j_left_foot | **Yes** |
| 33 | 26 | **RightWristRoll** | j_right_foot | **Yes** |
| 34 | 27 | **RightWristPitch** | j_waist_yaw | **Yes** |
| 35 | 28 | **RightWristYaw** | j_waist_roll | **Yes** |

The program controls SDK indices 12-28 (17 DOF: waist + left arm + right arm). Leg joints
0-11 are held at their initial position but not driven by the keyframe CSV.

## Method

- **Default pose**: Average of first 10 data rows (frames 0-9) from each `_recorded.csv`.
  This is the robot's stable standing posture at the start of Phase 0.
- **Keyframe first frame**: First data row from each `.csv` keyframe file.
- **Last 10 frames**: Average of last 10 data rows from each `_recorded.csv`. Used to
  verify the robot returned to its default pose after disengage.

## 1. Controlled Upper-Body Joints: Default Pose vs Keyframe First Frame

Both motions share the **same keyframe first frame** (except SDK 24 RightShoulderYaw,
which differs by 0.125 rad between zuoyi.csv and wave.csv). The default poses from the
two recordings are nearly identical (max diff 0.006 rad between sessions).

### Waist (SDK 12-14)

| SDK | Joint | Default | KF (zuoyi) | KF (wave) | Delta (z) | Delta (w) |
|-----|-------|---------|------------|-----------|-----------|-----------|
| 12 | WaistYaw | +0.0095 | -0.0231 | -0.0231 | -0.033 | -0.033 |
| 13 | WaistRoll | +0.0102 | -0.0156 | -0.0156 | -0.026 | -0.026 |
| 14 | WaistPitch | +0.2513 | +0.0868 | +0.0868 | **-0.164** | **-0.164** |

### Left Arm (SDK 15-21)

| SDK | Joint | Default | KF (both) | Delta | Flag |
|-----|-------|---------|-----------|-------|------|
| 15 | LeftShoulderPitch | +0.2783 | +0.1240 | **-0.154** | > 0.1 |
| 16 | LeftShoulderRoll | -0.0829 | +0.2398 | **+0.323** | > 0.1 |
| 17 | LeftShoulderYaw | +0.8206 | +1.3958 | **+0.575** | > 0.1 |
| 18 | LeftElbow | +0.0042 | +0.3531 | **+0.349** | > 0.1 |
| 19 | LeftWristRoll | +0.0059 | +0.1359 | **+0.130** | > 0.1 |
| 20 | LeftWristPitch | -0.0035 | -0.1166 | **-0.113** | > 0.1 |
| 21 | LeftWristYaw | +0.2551 | +0.0379 | **-0.217** | > 0.1 |

### Right Arm (SDK 22-28)

| SDK | Joint | Default | KF (zuoyi) | KF (wave) | Delta (z) | Delta (w) | Flag |
|-----|-------|---------|------------|-----------|-----------|-----------|------|
| 22 | RightShoulderPitch | -0.2871 | -0.1395 | -0.1395 | **+0.148** | **+0.148** | > 0.1 |
| 23 | RightShoulderRoll | +0.0969 | -0.1149 | -0.2398 | **-0.212** | **-0.337** | > 0.1 |
| 24 | RightShoulderYaw | +0.7844 | +1.4114 | +1.4114 | **+0.627** | **+0.627** | > 0.1 |
| 25 | RightElbow | -0.0066 | -0.4243 | -0.4243 | **-0.418** | **-0.418** | > 0.1 |
| 26 | RightWristRoll | +0.0029 | +0.0711 | +0.0711 | +0.068 | +0.068 | |
| 27 | RightWristPitch | -0.0021 | +0.1963 | +0.1963 | **+0.198** | **+0.198** | > 0.1 |
| 28 | RightWristYaw | (see note) | (see note) | (see note) | | | |

**Note on SDK 28 (RightWristYaw)**: This joint is used as the weight channel in the
csv_replay code (`kNotUsedJoint` = SDK 29), but SDK 28 itself is a real joint. Looking at
the data, the column 35 values differ between the recorded and keyframe files. In
`zuoyi_recorded.csv` and `wave_recorded.csv` col 35 = `j_waist_pitch` (SDK 28 =
RightWristYaw). The default is ~-0.002 and the keyframe value is +0.196, giving a delta
of ~+0.198.

## 2. Summary: Joints with |delta| > 0.1 rad (Default to First KF)

### Largest Deltas (Upper Body, Controlled Joints)

Sorted by absolute delta magnitude:

| Rank | SDK | Joint | Default | Keyframe | Delta | Direction |
|------|-----|-------|---------|----------|-------|-----------|
| 1 | 17 | LeftShoulderYaw | +0.821 | +1.396 | **+0.575** | Left arm swings forward |
| 2 | 25 | RightElbow | -0.007 | -0.424 | **-0.418** | Right elbow bends ~24 deg |
| 3 | 16 | LeftShoulderRoll | -0.083 | +0.240 | **+0.323** | Left shoulder lifts outward |
| 4 | 18 | LeftElbow | +0.004 | +0.353 | **+0.349** | Left elbow bends ~20 deg |
| 5 | 21 | LeftWristYaw | +0.255 | +0.038 | **-0.217** | Left wrist rotates |
| 6 | 24 | RightShoulderYaw | +0.784 | +1.411 | **+0.627** | Right arm swings forward |
| 7 | 23 | RightShoulderRoll (z) | +0.097 | -0.115 | **-0.212** | Right shoulder moves inward |
| 8 | 23 | RightShoulderRoll (w) | +0.097 | -0.240 | **-0.337** | Right shoulder moves inward (wave) |
| 9 | 27 | RightWristPitch | -0.002 | +0.196 | **+0.198** | Right wrist pitches up |
| 10 | 14 | WaistPitch | +0.251 | +0.087 | **-0.164** | Waist straightens slightly |
| 11 | 15 | LeftShoulderPitch | +0.278 | +0.124 | **-0.154** | Left shoulder pitches down |
| 12 | 22 | RightShoulderPitch | -0.287 | -0.140 | **+0.148** | Right shoulder pitches up |
| 13 | 19 | LeftWristRoll | +0.006 | +0.136 | **+0.130** | Left wrist rolls |
| 14 | 20 | LeftWristPitch | -0.004 | -0.117 | **-0.113** | Left wrist pitches down |

### Interpretation

The keyframe first frame represents a pose where:

- **Right arm is raised forward and rotated** (ShoulderYaw +0.6, Elbow bent -0.42,
  ShoulderRoll inward -0.21)
- **Left arm is also repositioned** (ShoulderYaw +0.6, Elbow bent +0.35,
  ShoulderRoll outward +0.32)
- **Waist slightly straightened** (Pitch -0.16)
- **Both wrists reoriented** for the gesture

This is a significant departure from the default standing pose. The Transition phase
(2 seconds, 0.5 rad/s clamp) must traverse these deltas. For the largest delta
(LeftShoulderYaw: 0.575 rad), at 0.5 rad/s this takes ~1.15s -- within the 2s window.
For RightShoulderYaw (0.627 rad), it takes ~1.25s. Both fit within the transition budget.

## 3. Return-to-Default Check (Disengage Verification)

After the disengage phase, the last 10 frames of each recording were compared to the
default pose. **Both motions returned to the default pose successfully.**

### Zuoyi: Last 10 Frames vs Default

| SDK | Joint | Default | Last 10 | Delta | Status |
|-----|-------|---------|---------|-------|--------|
| 12 | WaistYaw | +0.009 | +0.008 | -0.001 | OK |
| 13 | WaistRoll | +0.010 | +0.010 | 0.000 | OK |
| 14 | WaistPitch | +0.251 | +0.251 | 0.000 | OK |
| 15 | LeftShoulderPitch | +0.278 | +0.278 | 0.000 | OK |
| 16 | LeftShoulderRoll | -0.083 | -0.083 | 0.000 | OK |
| 17 | LeftShoulderYaw | +0.821 | +0.821 | 0.000 | OK |
| 18 | LeftElbow | +0.004 | +0.004 | 0.000 | OK |
| 19 | LeftWristRoll | +0.006 | +0.006 | 0.000 | OK |
| 20 | LeftWristPitch | -0.004 | -0.004 | 0.000 | OK |
| 21 | LeftWristYaw | +0.255 | +0.255 | 0.000 | OK |
| 22 | RightShoulderPitch | -0.287 | -0.287 | 0.000 | OK |
| 23 | RightShoulderRoll | +0.097 | +0.098 | 0.000 | OK |
| 24 | RightShoulderYaw | +0.785 | +0.785 | 0.000 | OK |
| 25 | RightElbow | -0.006 | -0.006 | 0.000 | OK |
| 26 | RightWristRoll | +0.003 | +0.003 | 0.000 | OK |
| 27 | RightWristPitch | -0.002 | -0.002 | 0.000 | OK |

All deltas < 0.001 rad. The robot returned to its default posture after disengage.

### Wave: Last 10 Frames vs Default

All deltas < 0.004 rad. The robot returned to its default posture after disengage.

### Leg Joints (held position check)

Leg joints (SDK 0-11) also remained stable throughout. Max drift from initial position
across both recordings was < 0.004 rad for all leg joints, confirming the leg-holding
strategy works correctly.

## 4. Zuoyi vs Wave: Keyframe Difference

The two motions share nearly identical first frames. Only one joint differs:

| CSV Col | SDK | Joint | Zuoyi KF | Wave KF | Diff |
|---------|-----|-------|----------|---------|------|
| 31 | 24 | RightShoulderYaw | -0.139 | -0.240 | 0.125 |

All other 28 joints are identical between the two keyframe files' first frames. This
suggests both motions were retargeted from a similar starting pose, with only a slight
variation in the right shoulder yaw orientation.

## 5. Recommendations

### Keyframe Adjustment

1. **No adjustment needed for disengage** -- the robot returns to its default pose
   reliably after every playback. The 4-second disengage (2s return + 2s ramp-down) is
   sufficient.

2. **Transition budget is adequate** -- the largest delta (RightShoulderYaw: 0.63 rad)
   traverses in ~1.3s at 0.5 rad/s, well within the 2s transition window. No change
   needed to `kTransitionMaxVel` or transition duration.

3. **Consider pre-rotating the keyframe first frame closer to default** if the transition
   feels jerky in practice. The current first frame requires the right arm to swing
   forward by ~36 degrees (LeftShoulderYaw) and the right elbow to bend ~24 degrees in
   2 seconds. While this fits the velocity clamp, a smoother entry could be achieved by
   blending the first few keyframe frames toward the default pose.

4. **Leg joint deltas are irrelevant** -- the large deltas in SDK 0-11 (up to 0.63 rad
   for LeftFoot) are in joints that the program does not control. The program reads the
   initial leg positions and holds them. The keyframe CSV values for leg joints are
   simply ignored by `csv_replay.cpp`.

5. **Column header names should be fixed** in the state_recorder to avoid confusion.
   The current header names (from LAFAN1 skeleton convention) do not match the SDK motor
   ordering. Consider using the SDK joint names (e.g. `left_hip_pitch` instead of
   `j_pelvis`).
