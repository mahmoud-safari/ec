singularity_base_command = "srun --job-name=re2_language_{} --output=jobs/{} --ntasks=1 --mem-per-cpu=5000 --gres=gpu --cpus-per-task 20 --time=10000:00 --qos=tenenbaum --partition=tenenbaum singularity exec -B /om2  --nv ../dev-container.img "

experiment_commands = []
jobs = []
job = 0

# Generates baseline experiments
EC_BASELINES = True
if EC_BASELINES:
        for enumerationTimeout in [720, 1800]:
            job_name = "re2_ec_learned_feature_compression_et_{}".format(enumerationTimeout)
            jobs.append(job_name)
            
            num_iterations = 5
            task_batch_size = 25
            test_every = 8 # Every 200 tasks 
            base_parameters = "--no-cuda --enumerationTimeout {} --testingTimeout 720 --recognitionEpochs 10 --biasOptimal --contextual --Helmholtz 0 --iterations {} --taskBatchSize {} --testEvery {}".format(enumerationTimeout, num_iterations, task_batch_size, test_every)
            
            base_command = "python bin/re2.py "
            
            singularity = singularity_base_command.format(job, job_name)
            command = singularity + base_command + base_parameters + " &"
            experiment_commands.append(command)
            job += 1

PRINT_JOBS = True
if PRINT_JOBS:
    # print the jobs.
    print('#!/bin/bash')
    print("module add openmind/singularity")
    for command in experiment_commands:
        print(command + "")