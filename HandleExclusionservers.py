import subprocess
import json
import time
import sys
import argparse
from tabulate import tabulate
class AWSServerManagerCLI:
    def __init__(self, config_path=None):
        self.region = 'us-east-2' 
        self.config_path = config_path 
        #or r"C:\programming\StartStopTest\asg.json" # Default ASG config file

    def _run_cli(self, command):
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True
            )
            return json.loads(result.stdout) if result.stdout else []
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Command failed: {e.stderr}", file=sys.stderr)
            sys.exit(1)

    def _print(self, message, status="INFO"):
        prefix = {"INFO": "[INFO]", "SUCCESS": "[SUCCESS]", "ERROR": "[ERROR]"}.get(status, "[INFO]")
        print(f"{prefix} {message}", flush=True)

    def load_config(self, config_path):
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self._print(f"Error loading config: {e}", "ERROR")
            sys.exit(1)

    def get_instances(self, cost_center, state=None, exclude_asg=False):
        filters = [f'Name=tag:CostCenter,Values={cost_center}']
        if state:
            filters.append(f'Name=instance-state-name,Values={state}')

        base_cmd = [
        'aws', 'ec2', 'describe-instances',
        '--filters'
        ]
        base_cmd.extend(filters)
    
        if exclude_asg:
            base_cmd.extend(['--query', 'Reservations[].Instances[?!contains(Tags[].Key, `aws:autoscaling:groupName`)].[InstanceId, Tags[?Key==`Name`].Value | [0], State.Name]'])
        else:
            base_cmd.extend(['--query', 'Reservations[].Instances[].[InstanceId, Tags[?Key==`Name`].Value | [0], State.Name]'])
    
        base_cmd.extend(['--region', self.region])

        instances = self._run_cli(base_cmd)

        if instances:
            table = tabulate(instances, headers=["Instance ID", "Name", "State"], tablefmt="grid")
            self._print("\n" + table)

        return instances       

def start_servers(self, cost_center, config, num_qa=None):
    env_config = config.get(cost_center, {})
    exclude_instances = env_config.get('exclude_instances', [])
    
    instances = self.get_instances(cost_center, 'stopped')
    
    instances = [i for i in instances if i[1] not in exclude_instances]
    
    qa_instances = [
        i for i in instances 
        if i[1] and i[1].startswith('BQE-QA-Automation-')
    ]
    other_instances = [i for i in instances if i not in qa_instances]
    
    if num_qa is not None:
        qa_instances.sort(key=lambda x: int(x[1].split('-')[-1]))
        
        # Select the first 'num_qa' QA instances
        selected_qa = qa_instances[:num_qa]
        
        # Combine selected QA instances with other instances
        instances_to_start = other_instances + selected_qa
    else:
        # If num_qa is not specified, start all non-excluded instances
        instances_to_start = instances
    
    # Start instances if any are selected
    if instances_to_start:
        instance_ids = [i[0] for i in instances_to_start]
        self._print(f"Starting {len(instance_ids)} instances in Cost Center {cost_center}")
        
        # Start instances and wait for them to be running
        self._run_cli(['aws', 'ec2', 'start-instances', '--instance-ids', *instance_ids])
        self._run_cli(['aws', 'ec2', 'wait', 'instance-running', '--instance-ids', *instance_ids])
    else:
        self._print("No instances to start in this Cost Center")
    
    # Handle Auto Scaling Groups (ASGs)
    asg_config = {k: v for k, v in env_config.items() if k != 'exclude_instances'}
    
    if asg_config:
        asg_data = [[asg_name, desired] for asg_name, desired in asg_config.items()]
        table = tabulate(asg_data, headers=["ASG Name", "Desired Capacity"], tablefmt="grid")
        self._print("\nStarting Auto Scaling Groups:\n" + table)
        
        for asg_name, desired in asg_config.items():
            self._print(f"Starting ASG {asg_name} with desired capacity {desired}")
            self._run_cli([
                'aws', 'autoscaling', 'update-auto-scaling-group',
                '--auto-scaling-group-name', asg_name,
                '--min-size', str(desired),
                '--max-size', str(desired),
                '--desired-capacity', str(desired),
                '--region', self.region
            ])
    
    self._print(f"Start operation for Cost Center {cost_center} completed successfully!", "SUCCESS")

def stop_servers(self, cost_center, config):
    try:
        asg_config = config.get(cost_center, {})

        if asg_config:
            asg_data = [[asg_name, 0] for asg_name in asg_config]
            table = tabulate(asg_data, headers=["ASG Name", "Desired Capacity"], tablefmt="grid")
            self._print("\nScaling Down Auto Scaling Groups:\n" + table)

            for asg_name in asg_config:
                try:
                    self._print(f"Scaling down ASG {asg_name}")    
                    self._run_cli([
                        'aws', 'autoscaling', 'update-auto-scaling-group',
                        '--auto-scaling-group-name', asg_name,
                        '--min-size', '0',
                        '--max-size', '0',
                        '--desired-capacity', '0',
                        '--region', self.region
                    ])
                except Exception as e:
                    self._print(f"Warning: Error scaling down ASG {asg_name}: {str(e)}", "ERROR")
                    continue
        instances = self.get_instances(cost_center, 'running', exclude_asg=True)

        # Check if instances exist first
        if instances:
            instance_ids = []
            for i in instances:
                if isinstance(i, list) and len(i) > 0:
                    instance_id = i[0]
                    if isinstance(instance_id, list) and len(instance_id) > 0:
                        instance_id = instance_id[0]
                    instance_ids.append(str(instance_id)) 

            if instance_ids:
                self._print(f"Stopping {len(instance_ids)} standalone instances")
                try:
                    self._run_cli(['aws', 'ec2', 'stop-instances', '--instance-ids', *instance_ids])
                except Exception as e:
                    self._print(f"Warning: Error stopping instances: {str(e)}", "ERROR")
            else:
                self._print("No valid instance IDs found to stop")
        else:
            self._print("No standalone instances found to stop")                

        self._print("Stop operation completed successfully!", "SUCCESS")
        return True

    except Exception as e:
        self._print(f"Error in stop_servers: {str(e)}", "ERROR")
        return False
    
def print_preview(self, cost_center, config):
    self._print(f"Previewing resources for Cost Center: {cost_center}")
    instances = self.get_instances(cost_center)
    if instances:
        self._print(f"Found {len(instances)} instances in Cost Center {cost_center}")
    else:
        self._print("No instances found in this Cost Center")
        
    asgs = config.get(cost_center, {})
    if asgs:
        asg_data = [[asg_name, desired] for asg_name, desired in asgs.items()]
        table = tabulate(asg_data, headers=["ASG Name", "Configured Capacity"], tablefmt="grid")
        self._print("\nConfigured Auto Scaling Groups:\n" + table)
    else:
        self._print("No Auto Scaling Groups configured for this Cost Center")


def main():
    parser = argparse.ArgumentParser(description='AWS Server Manager')
    parser.add_argument('-e', '--environment', required=True, help='Cost Center/Environment')
    parser.add_argument('-a', '--action', required=True, choices=['start', 'stop', 'preview'], help='Action to perform')
    parser.add_argument('-c', '--config', required=True, help='ASG config JSON file')
    parser.add_argument('-n', '--num-qa', type=int, help='Number of QA Automation instances to start')

    args = parser.parse_args()

    manager = AWSServerManagerCLI()
    config = manager.load_config(args.config)

    if args.action == 'preview':
        manager.print_preview(args.environment, config)
    elif args.action == 'start':
        manager.start_servers(args.environment, config, args.num_qa)
    elif args.action == 'stop':
        manager.stop_servers(args.environment, config)

if __name__ == '__main__':
    main()
