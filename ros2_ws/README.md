# ROS 2 Workspace Scaffold

This workspace contains the `inspection_interfaces` and `inspection_bridge` packages. The bridge exposes `/inspection/run`, uses Nav2 `NavigateToPose`, and defaults to a no-motion safety gate. The Python platform provides bounded retry/cancel handling and `Ros2TopicObservationProvider`; these require the target ROS 2 distribution at runtime. The workspace still does not claim a built or running ROS 2 node until `colcon build` and an authorized Isaac/robot smoke test pass.

For a machine-only demonstration that does not require ROS 2, use the project's
local virtual-world mode instead: `make virtual-demo`. It exercises the same
mission/report/artifact contracts with a kinematic placeholder robot and
dependency-free SVG renders.

## Build (ROS 2 environment required)

```bash
cd ros2_ws
source /opt/ros/humble/setup.bash   # replace with your installed ROS 2 distribution
colcon build --symlink-install
source install/setup.bash
ros2 interface show inspection_interfaces/msg/InspectionObservation
ros2 interface show inspection_interfaces/srv/RunInspection
ros2 run inspection_bridge inspection_bridge --ros-args \
  -p site_config_path:=/path/to/configs/site.json \
  -p allow_motion:=false
```

The observation message carries explicit sensor IDs, `frame_id`, and a JSON
domain extension so the platform can preserve provenance. Do not use raw
`/cmd_vel` as a substitute for Nav2 `NavigateToPose`; emergency stop and
vendor collision protection remain external safety gates.

If the selected ROS 2 distribution differs, verify package dependencies and build output in that environment. Do not claim the workspace builds until these commands actually pass.
