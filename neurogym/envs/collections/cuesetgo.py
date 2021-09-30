import numpy as np
import neurogym as ngym
from neurogym import spaces
from neurogym.wrappers.block import ScheduleEnvs
from neurogym.utils import scheduler


class CueSetGo(ngym.TrialEnv):
    """Agents have to produce different time intervals
    using different cues.
    """

    metadata = {
    }

    def __init__(self, dt=1, training=True, input_noise=0, target_threshold=0.05,
                 threshold_delay=50, target_ramp=True, wait_time=100, scenario=0):
        super().__init__(dt=dt)
        # Unpack Parameters

        # Several different intervals: their length and corresponding magnitude
        self.production_ind = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] 
        self.intervals = [720, 760, 800, 840, 880, 1420, 1460, 1500, 1540, 1580] 
        self.context_mag = np.add(np.multiply((0.3/950), self.intervals), (0.2-(0.3/950)*700))
         
        # WeberFraction as the production margin (acceptable deviation)
        # Leave out for now, reimplement later otherwise unfair
        # self.weberFraction = float((100-50)/(1500-800))
        # self.prod_margin = self.weberFraction
        self.scenario = scenario
        self.def_wait_time = wait_time
        self.training = training # training Label
        self.trial_nr = 1 # Trial Counter
        
        self.input_noise = input_noise # Input Noise Percentage
        self.target_threshold = target_threshold # Target Threshold Percentage
        self.threshold_delay = threshold_delay # Reward Delay after Threshold Crossing
        self.target_ramp = target_ramp

        # Binary Rewards for incorrect and correct
        self.rewards = {'incorrect': 0., 'correct': +1.}

        # Set Action and Observation Space
        # Allow Ramping between 0-1
        self.action_space = spaces.Box(0, 1, shape=(1,), dtype=np.float32)   
        # Context Cue: Burn Time followed by Cue 
        # Set Cue: Burn+Wait followed by Set Spike
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(2,), dtype=np.float32)

    def _new_trial(self, **kwargs):
        # Define Times
        self.wait_time = self.def_wait_time or int(self.rng.uniform(100, 200))
        self.burn = 50 # Duration of Burn period before context cue
        self.set = 20 # Duration of Set Period

        # Choose interval index (0-9) at Random
        if self.training == False:
            trial = {
                'production_ind': self.rng.choice(self.production_ind)
            }

        # Choose index by Cycling through all conditions for training
        if self.training == True: 
            trial = {
                'production_ind': self.production_ind[(self.trial_nr % len(self.production_ind))-1]
            }
        
        # Choose given Scenario
        if self.scenario is not None:
            trial = {
                'production_ind': self.scenario
            }

        trial.update(kwargs)

        # Select corresponding interval length
        trial['production'] = self.intervals[trial['production_ind']]

        # Calculate Trial Duration
        self.trial_duration = 2200
        # self.burn + self.waitTime + self.set + trial['production'] + self.threshold_delay + self.BackProp

        # Calculate corresponding context cue magnitude (Signal + 0.5% Noise)
        contextSignal = self.context_mag[trial['production_ind']]
        noiseSigmaContext = contextSignal * self.input_noise
        contextNoise = np.random.normal(0, noiseSigmaContext, (self.trial_duration-self.burn))
        contextCue = contextSignal + contextNoise

        # Define periods
        self.add_period('burn', duration= self.burn)
        self.add_period('cue', duration= self.trial_duration-self.burn, after='burn')
        self.add_period('wait', duration= self.wait_time, after='burn')
        self.add_period('set', duration= self.set, after='wait')
        self.add_period('production', duration=self.trial_duration-(self.set+self.wait_time+self.burn), after='set')

        # Set Burn to [0,0,0,0]
        ob = self.view_ob('burn')
        ob[:, 0] = 0
        ob[:, 1] = 0

        # Set Cue to contextCue
        ob = self.view_ob('cue')
        ob[:, 0] = contextCue

        # Set Set to 0.4
        ob = self.view_ob('set')
        ob[:, 1] = 0.4

        ob = self.view_ob()
        
        # Set Ground Truth as 0 at set and 1 at trial production with NaN/Target inbetween 
        if self.target_ramp == False:      
            gt = np.empty([int(((self.trial_duration)/self.dt)),])
            gt[:] = np.nan
            gt[0:self.burn+self.wait_time+self.set] = 0
            gt[self.burn+self.wait_time+self.set+int(trial['production']):self.burn+self.wait_time+self.set+int(trial['production'])+self.threshold_delay] = 1
            gt = np.reshape(gt, [int((self.trial_duration)/self.dt)] + list(self.action_space.shape))

        if self.target_ramp == True:
            gt = np.empty([int(((self.trial_duration)/self.dt)),])
            gt[:] = np.nan
            gt[self.burn:self.burn+self.wait_time+self.set] = 0
            gt[self.burn+self.wait_time+self.set+int(trial['production']):self.burn+self.wait_time+self.set+int(trial['production'])+self.threshold_delay] = 1
            gt[self.burn+self.wait_time+self.set:self.burn+self.wait_time+self.set+int(trial['production'])] = np.multiply(1/trial['production'], range(0, int(trial['production'])))
            gt = np.reshape(gt, [int((self.trial_duration)/self.dt)] + list(self.action_space.shape))

        self.set_groundtruth(gt)

        return trial, ob, gt

    def _step(self, action):
        trial = self.trial
        reward = 0
        ob = self.ob_now
        gt = self.gt_now
        NewTrial = False

        if self.in_period('burn'):
            self.set_reward = False
            self.threshold_reward = False
            self.t_threshold = 0

        if self.in_period('set'):
            if action <= 0.05: # Should start close to 0
                reward = self.rewards['correct']
                self.set_reward = True

            if self.set_reward:
                reward = self.rewards['correct']
                self.performance = 1

        if self.in_period('production'): 
            if  action >= 0.95: # Action is over Threshold
                t_prod = self.t - self.end_t['set']  # Measure Time from Set
                eps = abs(t_prod - trial[0]['production']) # Difference between Produced_Interval and Interval
                eps_threshold = int(trial[0]['production']*self.target_threshold) # Allowed margin to produced interval (normally WeberFraction)

                if eps <= eps_threshold: # If Difference is below Margin, Finish Trial
                    reward = self.rewards['correct']
                    self.ThresholdReward = True

            if self.threshold_reward == True:
                reward = self.rewards['correct']
                self.performance = 1
                self.t_threshold += 1

                if self.t_threshold >= self.threshold_delay: # Give reward threshold_delay steps after Success
                    NewTrial = True
                    self.threshold_reward = False

            if self.t > self.trial_duration:
                NewTrial = True 

        if NewTrial == True:
            self.trial_nr += 1

        return ob, reward, NewTrial, {
            'new_trial': NewTrial, 
            'gt': gt, 
            'SetStart': self.wait_time+self.burn, 
            'Interval': trial[0]['production'], 
            'threshold_delay': self.threshold_delay}



class ReadySetGo_SinglePrior(ngym.TrialEnv):
    # RSG with Reinforcement Learning:
    """Agents have to estimate and produce different time intervals
    using different effectors (actions).
    """
    def __init__(self, dt=1, training=True, input_noise=0.01 , target_threshold=0.05,
                 threshold_delay=50, target_ramp=True, wait_time=50, scenario=0):
        super().__init__(dt=dt)

        # Several different intervals with their corresponding their length 
        self.production_ind = [0, 1, 2, 3, 4] 
        self.intervals = [480, 560, 640, 720, 800]
        # Short Context Cue:
        self.context_mag = 0.3
        
        # WeberFraction as the production margin (acceptable deviation)
        # Leave out for now, reimplement later otherwise unfair
        # self.weberFraction = float((100-50)/(1500-800))
        # self.prod_margin = self.weberFraction
        self.scenario = scenario
        self.def_wait_time = wait_time
        self.training = training # training Label
        self.trial_nr = 1 # Trial Counter
        self.input_noise = input_noise # Input Noise Percentage
        self.target_threshold = target_threshold # Target Threshold Percentage, Later becomes WeberFraction
        self.threshold_delay = threshold_delay
        self.target_ramp = target_ramp
        # Binary Rewards for incorrect and correct
        self.rewards = {'incorrect': 0., 'correct': +1.}    

        # Set Action and Observation Space
        # Allow Ramping between 0-1
        self.action_space = spaces.Box(0, 1, shape=(1,), dtype=np.float32)   
        # Context Cue: Burn Time followed by Cue
        # Ready-Set Cue: Burn+Wait followed by Ready-Set Spike
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(2,), dtype=np.float32)

    def _new_trial(self, **kwargs):
        # Define Times
        self.wait_time = self.def_wait_time or int(self.rng.uniform(100, 200))
        self.burn = 50
        self.spike = 20

        # Choose index (0-9) at Random
        if self.training == False:
            trial = {
                'production_ind': self.rng.choice(self.production_ind)
            }

        # Choose index by Cycling through all conditions for training
        if self.training == True: 
            trial = {
                'production_ind': self.production_ind[(self.trial_nr % len(self.production_ind))-1]
            }
        
        # Choose given Scenario
        if self.scenario is not None:
            trial = {
                'production_ind': self.scenario
            }

        # Select corresponding interval
        trial['production'] = self.intervals[trial['production_ind']]

        # Calculate Trial Duration
        self.trial_duration = 2000
        
        # Select corresponding context cue (Signal + input_noise)
        contextSignal = self.context_mag
        noiseSigmaContext = contextSignal * self.input_noise
        contextNoise = np.random.normal(0, noiseSigmaContext, (self.trial_duration-self.burn))
        contextCue = contextSignal + contextNoise

        # Define periods
        self.add_period('burn', duration= self.burn)
        self.add_period('cue', duration= self.trial_duration-self.burn, after='burn')
        self.add_period('wait', duration= self.wait_time, after='burn')
        self.add_period('ready', duration= self.spike, after='wait')
        self.add_period('estimation', duration= trial['production'], after='ready')
        self.add_period('set', duration= self.spike, after='estimation')
        self.add_period('production', duration=self.trial_duration-(self.spike+trial['production']+self.spike+self.wait_time+self.burn), after='set')

        # Set Burn to 0
        ob = self.view_ob('burn')
        ob[:, 0] = 0
        ob[:, 1] = 0

        # Set Cue to contextCue
        ob = self.view_ob('cue')
        ob[:, 0] = contextCue

        # Set Wait to contextCue
        ob = self.view_ob('wait')
        ob[:, 1] = 0

        # Set Ready to 0.4
        ob = self.view_ob('ready')
        ob[:, 1] = 0.4

        # Set Estimation to 0
        ob = self.view_ob('estimation')
        ob[:, 1] = 0

        # Set Set to 0.4
        ob = self.view_ob('set')
        ob[:, 1] = 0.4

        # Set Production to 0
        ob = self.view_ob('production')
        ob[:, 1] = 0

        ob = self.view_ob()

        # Set Ground Truth as 0 at Set and 1 at Trial Production with NaN or Ramp inbetween
        gt = np.empty([int(((self.trial_duration)/self.dt)),])
        gt[:] = np.nan
        gt[self.burn+self.wait_time:self.burn+self.wait_time+self.spike] = 0
        gt[self.burn+self.wait_time+self.spike+trial['production']:self.burn+self.wait_time+self.spike+trial['production']+self.spike] = 0
        if self.target_ramp == True:
            t_ramp = range(0, int(trial['production']))
            gt_ramp = np.multiply(1/trial['production'], t_ramp)
            gt[self.burn+self.wait_time+self.spike+trial['production']+self.spike:self.burn+self.wait_time+self.spike+trial['production']+self.spike+trial['production']] = gt_ramp

        gt[self.burn+self.wait_time+self.spike+trial['production']+self.spike+trial['production']:self.burn+self.wait_time+self.spike+trial['production']+self.spike+trial['production']+self.threshold_delay] = 1
        gt = np.reshape(gt, [int((self.trial_duration)/self.dt)] + list(self.action_space.shape))
        self.set_groundtruth(gt)

        return trial, ob, gt

    def _step(self, action):
        trial = self.trial
        reward = 0
        ob = self.ob_now
        gt = self.gt_now
        NewTrial = False

        if self.in_period('burn'):
            self.set_reward = False
            self.threshold_reward = False
            self.t_threshold = 0

        if self.in_period('set'):
            if action <= 0.05: # Should start close to 0
                reward = self.rewards['correct']
                self.set_reward = True

            if self.set_reward:
                reward = self.rewards['correct']
                self.performance = 1

        if self.in_period('production'):
            if  action >= 0.95: # Action is over Threshold
                t_prod = self.t - self.end_t['set']  # Measure Time from Set
                eps = abs(t_prod - trial[0]['production']) # Difference between Produced_Interval and Interval
                eps_threshold = int(trial[0]['production']*self.target_threshold) # Allowed margin to produced interval

                if eps <= eps_threshold: # If Difference is below Margin, Finish Trial
                    reward = self.rewards['correct']
                    self.threshold_reward = True

            if self.threshold_reward == True:
                reward = self.rewards['correct']
                self.performance = 1
                self.t_threshold += 1

                if self.t_threshold >= self.threshold_delay: # Give reward ThresholDelay steps after Success
                    NewTrial = True
                    self.threshold_reward = False

            if self.t > self.trial_duration:
                NewTrial = True

        if NewTrial == True:
            self.trial_nr += 1

        return ob, reward, NewTrial, {
            'new_trial': NewTrial, 
            'TrialDuration': self.trial_duration,
            'gt': gt,
            'Interval': trial[0]['production'],
            'SetStart': self.spike+trial[0]['production']+self.spike+self.wait_time+self.burn
            }


class ReadySetGo_DoublePrior(ngym.TrialEnv):
    # RSG with Reinforcement Learning:
    """Agents have to estimate and produce different time intervals
    using different effectors (actions).
    """
    def __init__(self, dt=1, training=True, input_noise=0, target_threshold=0.05,
                 threshold_delay=50, target_ramp=True, wait_time=50, scenario=0):
        super().__init__(dt=dt)
        # Several different intervals with their corresponding their length 
        self.production_ind = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] 
        self.intervals = [480, 560, 640, 720, 800, 800, 900, 1000, 1100, 1200] 
        # Possible Context Cues (Short/Long):
        self.context_mag = [0.3, 0.4]
        
        # WeberFraction as the production margin (acceptable deviation)
        # Leave out for now, reimplement later otherwise unfair
        # self.weberFraction = float((100-50)/(1500-800))
        # self.prod_margin = self.weberFraction
        self.scenario = scenario
        self.def_wait_time = wait_time
        self.training = training # training Label
        self.trial_nr = 1 # Trial Counter
        self.input_noise = input_noise # Input Noise Percentage
        self.target_threshold = target_threshold # Target Threshold Percentage, Later becomes WeberFraction
        self.threshold_delay = threshold_delay
        self.target_ramp = target_ramp

        # Binary Rewards for incorrect and correct
        self.rewards = {'incorrect': 0., 'correct': +1.}    

        # Set Action and Observation Space
        # Allow Ramping between 0-1
        self.action_space = spaces.Box(0, 1, shape=(1,), dtype=np.float32)   
        # Context Cue: Burn Time followed by Cue
        # Ready-Set Cue: Burn+Wait followed by Ready-Set Spike
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(2,), dtype=np.float32)

    def _new_trial(self, **kwargs):
        # Define Times
        self.wait_time = self.def_wait_time or int(self.rng.uniform(100, 200))
        self.burn = 50
        self.spike = 20

        # Choose index (0-9) at Random
        if self.training == False:
            trial = {
                'production_ind': self.rng.choice(self.production_ind)
            }

        # Choose index by Cycling through all conditions for training
        if self.training == True: 
            trial = {
                'production_ind': self.production_ind[(self.trial_nr % len(self.production_ind))-1]
            }
        
        # Choose given Scenario
        if self.scenario is not None:
            trial = {
                'production_ind': self.scenario
            }

        # Select corresponding interval
        trial['production'] = self.intervals[trial['production_ind']]

        # Calculate Trial Duration
        self.trial_duration = 3000

        # Select corresponding context cue (Signal + input_noise)
        if trial['production_ind'] < 5:
            contextSignal = self.context_mag[0]
        else:
            contextSignal = self.context_mag[1]

        noiseSigmaContext = contextSignal * self.input_noise
        contextNoise = np.random.normal(0, noiseSigmaContext, (self.trial_duration-self.burn))
        contextCue = contextSignal + contextNoise

        # Define periods
        self.add_period('burn', duration= self.burn)
        self.add_period('cue', duration= self.trial_duration-self.burn, after='burn')
        self.add_period('wait', duration= self.wait_time, after='burn')
        self.add_period('ready', duration= self.spike, after='wait')
        self.add_period('estimation', duration= trial['production'], after='ready')
        self.add_period('set', duration= self.spike, after='estimation')
        self.add_period('production', duration=self.trial_duration-(self.spike+trial['production']+self.spike+self.wait_time+self.burn), after='set')

        # Set Burn to 0
        ob = self.view_ob('burn')
        ob[:, 0] = 0
        ob[:, 1] = 0

        # Set Cue to contextCue
        ob = self.view_ob('cue')
        ob[:, 0] = contextCue

        # Set Wait to contextCue
        ob = self.view_ob('wait')
        ob[:, 1] = 0

        # Set Ready to 0.4
        ob = self.view_ob('ready')
        ob[:, 1] = 0.4

        # Set Estimation to 0
        ob = self.view_ob('estimation')
        ob[:, 1] = 0

        # Set Set to 0.4
        ob = self.view_ob('set')
        ob[:, 1] = 0.4

        # Set Production to 0
        ob = self.view_ob('production')
        ob[:, 1] = 0

        ob = self.view_ob()

        # Set Ground Truth as 0 at Set and 1 at Trial Production with NaN or Ramp inbetween
        gt = np.empty([int(((self.trial_duration)/self.dt)),])
        gt[:] = np.nan
        gt[self.burn+self.wait_time:self.burn+self.wait_time+self.spike] = 0
        gt[self.burn+self.wait_time+self.spike+trial['production']:self.burn+self.wait_time+self.spike+trial['production']+self.spike] = 0
        if self.target_ramp == True:
            t_ramp = range(0, int(trial['production']))
            gt_ramp = np.multiply(1/trial['production'], t_ramp)
            gt[self.burn+self.wait_time+self.spike+trial['production']+self.spike:self.burn+self.wait_time+self.spike+trial['production']+self.spike+trial['production']] = gt_ramp

        gt[self.burn+self.wait_time+self.spike+trial['production']+self.spike+trial['production']:self.burn+self.wait_time+self.spike+trial['production']+self.spike+trial['production']+self.threshold_delay] = 1
        gt = np.reshape(gt, [int((self.trial_duration)/self.dt)] + list(self.action_space.shape))
        self.set_groundtruth(gt)

        return trial, ob, gt

    def _step(self, action):
        trial = self.trial
        reward = 0
        ob = self.ob_now
        gt = self.gt_now
        NewTrial = False

        if self.in_period('burn'):
            self.set_reward = False
            self.threshold_reward = False
            self.t_threshold = 0

        if self.in_period('set'):
            if action <= 0.05: # Should start close to 0
                reward = self.rewards['correct']
                self.set_reward = True

            if self.set_reward:
                reward = self.rewards['correct']
                self.performance = 1

        if self.in_period('production'):
            if  action >= 0.95: # Action is over Threshold
                t_prod = self.t - self.end_t['set']  # Measure Time from Set
                eps = abs(t_prod - trial[0]['production']) # Difference between Produced_Interval and Interval
                eps_threshold = int(trial[0]['production']*self.target_threshold) # Allowed margin to produced interval

                if eps <= eps_threshold: # If Difference is below Margin, Finish Trial
                    reward = self.rewards['correct']
                    self.threshold_reward = True

            if self.threshold_reward == True:
                reward = self.rewards['correct']
                self.performance = 1
                self.t_threshold += 1

                if self.t_threshold >= self.threshold_delay: # Give reward ThresholDelay steps after Success
                    NewTrial = True
                    self.threshold_reward = False

            if self.t > self.trial_duration:
                NewTrial = True

        if NewTrial == True:
            self.trial_nr += 1

        return ob, reward, NewTrial, {
            'new_trial': NewTrial, 
            'TrialDuration': self.trial_duration,
            'gt': gt,
            'Interval': trial[0]['production'],
            'SetStart': self.spike+trial[0]['production']+self.spike+self.wait_time+self.burn,
            }


def cuesetgo(n_conds=10, **kwargs):
    input_noise = 0  # Input Noise Percentage
    target_threshold = 0.05  # Allowed Target Deviation Percentage
    threshold_delay = 50  # Delay after Threshold is reached
    wait_time = 100  # Wait after start for context cue
    target_ramp = True  # Ramp or NaN Target
    training = True
    env_kwargs = {'training': training, 'input_noise': input_noise,
                  'target_threshold': target_threshold,
                  'threshold_delay': threshold_delay, 'target_ramp': target_ramp,
                  'wait_time': wait_time, 'scenario': 0}
    env_kwargs.update(kwargs)
    env_list = []
    for scenario in range(n_conds):
        env_kwargs['scenario'] = scenario
        env_list.append(CueSetGo(**env_kwargs))
    schedule = scheduler.SequentialSchedule(len(env_list))
    env = ScheduleEnvs(env_list, schedule, env_input=False)
    return env


def readysetgo_sp(n_conds=10, **kwargs):
    input_noise = 0.01  # Input Noise Percentage
    target_threshold = 0.05  # Allowed Target Deviation Percentage
    threshold_delay = 50  # Delay after Threshold is reached
    wait_time = 50  # Wait after start for context cue
    target_ramp = True  # Ramp or NaN Target
    training = True
    scenario = 0
    env_kwargs = {'training': training, 'input_noise': input_noise,
                  'target_threshold': target_threshold,
                  'threshold_delay': threshold_delay, 'target_ramp': target_ramp,
                  'wait_time': wait_time, 'scenario': 0}
    env_kwargs.update(kwargs)
    env_list = []
    for scenario in range(n_conds):
        env_kwargs['scenario'] = scenario
        env_list.append(ReadySetGo_SinglePrior(**env_kwargs))
    schedule = scheduler.SequentialSchedule(len(env_list))
    env = ScheduleEnvs(env_list, schedule, env_input=False)
    return env


def readysetgo_dp(n_conds=10, **kwargs):
    input_noise = 0  # Input Noise Percentage
    target_threshold = 0.05  # Allowed Target Deviation Percentage
    threshold_delay = 50  # Delay after Threshold is reached
    wait_time = 50  # Wait after start for context cue
    target_ramp = True  # Ramp or NaN Target
    training = True
    scenario = 0
    env_kwargs = {'training': training, 'input_noise': input_noise,
                  'target_threshold': target_threshold,
                  'threshold_delay': threshold_delay, 'target_ramp': target_ramp,
                  'wait_time': wait_time, 'scenario': 0}
    env_kwargs.update(kwargs)
    env_list = []
    for scenario in range(n_conds):
        env_kwargs['scenario'] = scenario
        env_list.append(ReadySetGo_DoublePrior(**env_kwargs))
    schedule = scheduler.SequentialSchedule(len(env_list))
    env = ScheduleEnvs(env_list, schedule, env_input=False)
    return env
