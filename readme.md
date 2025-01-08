
# Non-Stationarity in the Train-Scheduling-Problem: Leveraging Effects of Curriculum Learning #
This repository contains the code and resources for my Bachelor Thesis:Non-Stationarity in the Train-Scheduling-Problem:
Leveraging Effects of Curriculum Learning
- This Thesis is the basis of the following [Paper: Mitigating the Stability-Plasticity Dilemma in Adaptive Train Scheduling with Curriculum-Driven Continual DQN Expansion](https://arxiv.org/pdf/2408.09838) ([Code Here!](https://github.com/EtienneKuenzel/Continual-DQN-Expansion))
- Simulator used is [Flatland-RL](https://github.com/flatland-association/flatland-rl) by AICrowd

## Abstract ##
Trains are a long-existing medium of transportation and supply chain management, which are
still of the utmost importance for global and local transportation of goods and individuals to
the present day. With the significance of trains, this bachelor thesis delves into the intricacies
of train scheduling, the problem of controlling multiple trains, and adapting to unforeseen problems.
While Operations Research methodologies currently dominate train scheduling, their limitations
in adaptability and computational efficiency prompt exploration into alternative approaches.
This thesis investigates the application of Multi-Agent Reinforcement Learning in the train
scheduling problem and highlights the advantages of designing training curricula derived from
a deconstruction of the train scheduling problem.
By utilizing this Custom Curriculum, we were able to improve the mean done rate(number of
trains reaching their destination) of a DDDQN algorithm by about 160% compared to using No
Curriculum.
We further explore adaptations to the DDDQN addressing the Non-Stationarity, which is introduced with the changing environments of the curricula to leverage the positive effects of the
custom curricula.
The adaptation that improved mean done rate the most, when evaluated in an environment not
being part of the training data, was the utilization of rational pad´e activation units(a type of
learnable activation function), which increased the mean done rate by roughly 232%, but also
the use of elastic weight consolidation yielded an improvement of 195%, both showing us that
we are able to leverage the effects of a curriculum by using adaptations to Non-Stationarity,
commonly used in continual/lifelong reinforcement learning setting.
The insights gained contribute to making RL more applicable to logistics and supply chain
management tasks, enhancing efficiency and adaptability across them, but they need further
investigation due to the results displaying high variance.



