from .ppo_default import PPODefaultCfg


class PPOMovePolicyPlantCfg(PPODefaultCfg):
    name = "ppo_move-policy_plant"


class PPOHighLevelPolicyPlantCfg(PPODefaultCfg):
    name = "ppo_high-level-policy_plant"
    # This class is here to be able to modify the hyperparameters for PPO independently from the low level policy
    class runner(PPODefaultCfg.runner):
        max_iterations = 2500
        save_interval = 50  # check for potential saves every this many iterations
        num_steps_per_env = 24 // 4  # per iteration
