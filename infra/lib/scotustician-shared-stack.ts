import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

export class ScotusticianSharedStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly cluster: ecs.Cluster;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';
    
        super(scope, id, {
          ...props,
          synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
        });

    this.vpc = new ec2.Vpc(this, 'ScotusticianVpc', { maxAzs: 2 });
    this.cluster = new ecs.Cluster(this, 'ScotusticianCluster', {
      vpc: this.vpc,
    });

    const instanceType = new ec2.InstanceType('g4dn.xlarge');

    const gpuAmi = ec2.MachineImage.lookup({
      name: 'amzn2-ami-ecs-gpu*',
      owners: ['amazon'],
    });

    const autoScalingGroup = new autoscaling.AutoScalingGroup(this, 'GPUFleet', {
      vpc: this.vpc,
      instanceType,
      machineImage: gpuAmi,
      minCapacity: 1,
      requireImdsv2: true,
    });

    const capacityProvider = new ecs.AsgCapacityProvider(this, 'AsgCapacityProvider', {
      autoScalingGroup,
    });

    this.cluster.addAsgCapacityProvider(capacityProvider);
  }
}
