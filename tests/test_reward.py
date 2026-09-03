from memory_core.memory_manager.reward import Episode, compute_reward, compute_rewards


def test_compute_reward_matches_qa_outcome():
    assert compute_reward(Episode("e1", qa_correct=True)) == 1.0
    assert compute_reward(Episode("e2", qa_correct=False)) == 0.0


def test_compute_rewards_batch():
    episodes = [Episode("e1", True), Episode("e2", False), Episode("e3", True)]
    assert compute_rewards(episodes) == [1.0, 0.0, 1.0]
