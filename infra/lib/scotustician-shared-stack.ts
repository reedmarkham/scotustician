import { Stack, StackProps, DefaultStackSynthesizer } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';

export interface ScotusticianSharedStackProps extends StackProps {}

export class ScotusticianSharedStack extends Stack {
  public readonly vpc: ec2.Vpc;
  public readonly cluster: ecs.Cluster;

  constructor(scope: Construct, id: string, props?: ScotusticianSharedStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({
        qualifier: qualifier,
      }),
    });

    this.vpc = new ec2.Vpc(this, 'ScotusticianVpc', {
      maxAzs: 2,
    });

    this.cluster = new ecs.Cluster(this, 'ScotusticianCluster', {
      vpc: this.vpc,
    });

    const gpuAmi = ec2.MachineImage.lookup({
      name: 'amzn2-ami-ecs-gpu*',
      owners: ['amazon'],
    });

    const autoScalingGroup = new autoscaling.AutoScalingGroup(this, 'GPUFleet', {
      vpc: this.vpc,
      instanceType: new ec2.InstanceType('g4dn.xlarge'),
      machineImage: gpuAmi,
      minCapacity: 1,
    });

    const capacityProvider = new ecs.AsgCapacityProvider(this, 'AsgCapacityProvider', {
      autoScalingGroup,
    });

    this.cluster.addAsgCapacityProvider(capacityProvider);
  }
}
