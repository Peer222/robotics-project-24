import numpy as np
from pathlib import Path

from isaacgym import gymapi
from .go2_default import GO2DefaultCfg


class GO2HighLevelPlantPolicyCfg(GO2DefaultCfg):
    name = "go2_high-level-policy_plant"

    class asset(GO2DefaultCfg.asset):
        file = str(Path(__file__).parents[2] / "assets/robots" / "go2_with_watering" / "urdf/go2.urdf")

    class low_level_policy:
        path = Path(__file__).parents[2] / "models" / "low-level_policy" / "low_lvl_model.pt"
        num_observations = 48
        num_actions = 12
        steps_per_high_level_action = 4

    class env(GO2DefaultCfg.env):
        num_envs = 128
        num_observations = 3 + 12
        num_privileged_obs = None  # if not None a priviledge_obs_buf will be returned by step() (critic obs for assymetric training). None is returned otherwise
        num_actions = 3
        episode_length_s = 8  # episode length in seconds

    class init_state(GO2DefaultCfg.init_state):
        pos = [0.0, 0.0, 0.42]  # x,y,z [m]
        random_rotation = True
        maximum_location_offset = 0.0 # Works but might result in collisions with other objects on reset

    class domain_rand(GO2DefaultCfg.domain_rand):
        push_robots = False

    class rewards(GO2DefaultCfg.rewards):
        # Parameters for custom rewards HERE
        only_positive_rewards = False # if true negative total rewards are clipped at zero (avoids early termination problems)

        class scales():
            # only rewards that have a scale will be added (reward is named "_reward_{SCALE_NAME}")
            plant_closeness = 5.0
            plant_ahead = 5.0
            obstacle_closeness = 0.0
            minimize_rotation = 0.5

    # robot camera:
    class camera:
        horizontal_fov = 120
        width = 128
        height = 72
        split_to_width = 12
        enable_tensors = True
        vec_from_body_center = gymapi.Vec3(0.34, 0, 0.021)  # Should be closest to reality: (0.34, 0, 0.021)m
        rot_of_camera = gymapi.Quat.from_axis_angle(
            gymapi.Vec3(0, 0, 1), np.radians(0)
        )
