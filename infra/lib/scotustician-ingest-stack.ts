import { Stack, StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';

export interface ScotusticianIngestStackProps extends StackProps {
  cluster: ecs.Cluster;
  vpc: ec2.IVpc;
}

export class ScotusticianIngestStack extends Stack {
  constructor(scope: Construct, id: string, props: ScotusticianIngestStackProps) {
    super(scope, id, props);

    const image = new ecr_assets.DockerImageAsset(this, 'IngestImage', {
      directory: '../ingest',
    });

    const taskDefinition = new ecs.FargateTaskDefinition(this, 'IngestTaskDef');
    taskDefinition.addContainer('IngestContainer', {
      image: ecs.ContainerImage.fromDockerImageAsset(image),
      memoryLimitMiB: 512,
      cpu: 256,
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'ingest' }),
    });

    new ecs.FargateService(this, 'IngestService', {
      cluster: props.cluster,
      taskDefinition,
      desiredCount: 1,
    });
  }
}
