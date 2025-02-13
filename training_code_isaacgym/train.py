from typing import Tuple
import os
from pathlib import Path

from isaacgym import gymutil

from legged_gym.envs import *
from legged_gym.utils import task_registry

from .environments import task
from .configs import (
    robots as robot_configs,
    scenes as scene_configs,
    algorithms as alg_configs,
)


robots = {
    "go2_default": robot_configs.GO2DefaultCfg(),
    "go2_low-level-policy": robot_configs.GO2LowLevelPolicyCfg(),
    "go2_high-level-policy_plant": robot_configs.GO2HighLevelPlantPolicyCfg(),
}
scenes = {
    "ground_plane": scene_configs.BaseSceneCfg(),
    "empty_room_10x10": scene_configs.EmptyRoom10x10Cfg(),
    "empty_room_5x5": scene_configs.EmptyRoom5x5Cfg(),
    "plant_environment": scene_configs.PlantEnvironmentCfg(),
    "single_plant": scene_configs.SinglePlantCfg(),
    "single_plant_with_obstacles": scene_configs.SinglePlantWithObstaclesCfg(),
}
algorithms = {
    "ppo_default": alg_configs.PPODefaultCfg(),
    "ppo_move-policy_plant": alg_configs.PPOMovePolicyPlantCfg(),
    "ppo_high-level-policy_plant": alg_configs.PPOHighLevelPolicyPlantCfg(),
}
robot_class = {
    "go2_default_class": task.CustomLeggedRobot,
    "go2_high-level-policy_plant_class": task.HighLevelPlantPolicyLeggedRobot,
}



def get_args():
    custom_parameters = [
        {
            "name": "--resume",
            "action": "store_true",
            "default": False,
            "help": "Resume training from a checkpoint",
        },
        {
            "name": "--load_run",
            "type": str,
            "help": "Name of the run to load when resume=True. If -1: will load the last run. Overrides config file if provided.",
        },
        {
            "name": "--checkpoint",
            "type": int,
            "help": "Saved model checkpoint number. If -1: will load the last checkpoint. Overrides config file if provided.",
        },
        {
            "name": "--headless",
            "action": "store_true",
            "default": False,
            "help": "Force display off at all times",
        },
        {
            "name": "--horovod",
            "action": "store_true",
            "default": False,
            "help": "Use horovod for multi-gpu training",
        },
        {
            "name": "--rl_device",
            "type": str,
            "default": "cuda:0",
            "help": "Device used by the RL algorithm, (cpu, gpu, cuda:0, cuda:1 etc..)",
        },
        {
            "name": "--num_envs",
            "type": int,
            "help": "Number of environments to create. Overrides config file if provided.",
        },
        {
            "name": "--seed",
            "type": int,
            "help": "Random seed. Overrides config file if provided.",
        },
        {
            "name": "--max_iterations",
            "type": int,
            "help": "Maximum number of training iterations. Overrides config file if provided.",
        },
        {
            "name": "--experiment_name",
            "type": str,
            "help": "Name of the experiment to run or load. Overrides config file if provided.",
        },
        {
            "name": "--run_name",
            "type": str,
            "help": "Name of the run. Overrides config file if provided.",
        },
        {
            "name": "--robot",
            "type": str,
            "default": "go2_default",
            "help": f"Name of robot config to use. Options: {list(robots.keys())}",
        },
        {
            "name": "--robot_class",
            "type": str,
            "default": "go2_default_class",
            "help": f"Robot class to use. Options: {list(robot_class.keys())}, (see environments/task.py)",
        },
        {
            "name": "--scene",
            "type": str,
            "default": "ground_plane",
            "help": f"Name of scene config to use. Options: {list(scenes.keys())}",
        },
        {
            "name": "--algorithm",
            "type": str,
            "default": "ppo_default",
            "help": f"Name of algorithm config to use. Options: {list(algorithms.keys())}",
        },
    ]
    # parse arguments
    args = gymutil.parse_arguments(
        description="RL Policy", custom_parameters=custom_parameters
    )

    # name allignment
    args.sim_device_id = args.compute_device_id
    args.sim_device = args.sim_device_type
    if args.sim_device == "cuda":
        args.sim_device += f":{args.sim_device_id}"
    return args


def get_configs(
    args,
) -> Tuple[
    robot_configs.GO2DefaultCfg, scene_configs.BaseSceneCfg, alg_configs.PPODefaultCfg
]:
    return (
        robots[args.robot],
        scenes[args.scene],
        algorithms[args.algorithm],
        robot_class[args.robot_class],
    )


def train(task_name, args):
    env, env_cfg = task_registry.make_env(name=task_name, args=args)
    ppo_runner, train_cfg = task_registry.make_alg_runner(
        env=env, name=task_name, args=args, log_root=Path(os.getcwd()) / "logs"
    )
    ppo_runner.learn(
        num_learning_iterations=train_cfg.runner.max_iterations,
        init_at_random_ep_len=True,
    )


if __name__ == "__main__":
    args = get_args()
    configs = get_configs(args)

    task_name = task.register_task(*configs)
    train(task_name, args)
