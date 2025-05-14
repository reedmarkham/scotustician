import { Stack, StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';

export class ScotusticianEtlStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const vpc = new ec2.Vpc(this, 'EtlVpc', { maxAzs: 2 });

    const cluster = new ecs.Cluster(this, 'EtlCluster', { vpc });

    const image = new ecr_assets.DockerImageAsset(this, 'EtlImage', {
      directory: '../etl',
    });

    const taskDefinition = new ecs.FargateTaskDefinition(this, 'EtlTaskDef');
    taskDefinition.addContainer('EtlContainer', {
      image: ecs.ContainerImage.fromDockerImageAsset(image),
      memoryLimitMiB: 512,
      cpu: 256,
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'etl' }),
    });

    new ecs.FargateService(this, 'EtlService', {
      cluster,
      taskDefinition,
      desiredCount: 1,
    });
  }
}
