import { Stack, StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';

export class ScotusticianTransformersStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const vpc = new ec2.Vpc(this, 'TransformersVpc', { maxAzs: 2 });

    const cluster = new ecs.Cluster(this, 'TransformersCluster', { vpc });

    const autoScalingGroup = new autoscaling.AutoScalingGroup(this, 'GPUFleet', {
      vpc,
      instanceType: new ec2.InstanceType('g4dn.xlarge'),
      machineImage: ecs.EcsOptimizedImage.amazonLinux2(),
      minCapacity: 1,
    });

    cluster.addAutoScalingGroup(autoScalingGroup);

    const image = new ecr_assets.DockerImageAsset(this, 'TransformersImage', {
      directory: '../transformers',
    });

    const taskDefinition = new ecs.Ec2TaskDefinition(this, 'TransformersTaskDef');
    const container = taskDefinition.addContainer('TransformersContainer', {
      image: ecs.ContainerImage.fromDockerImageAsset(image),
      memoryLimitMiB: 8192,
      cpu: 1024,
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'transformers' }),
    });

    container.addResourceRequirements({
      type: ecs.ResourceType.GPU,
      value: '1'
    });

    new ecs.Ec2Service(this, 'TransformersService', {
      cluster,
      taskDefinition,
      desiredCount: 1,
    });
  }
}
