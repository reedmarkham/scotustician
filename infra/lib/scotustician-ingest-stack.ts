import { Stack, StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import { DefaultStackSynthesizer } from 'aws-cdk-lib';

export interface ScotusticianIngestStackProps extends StackProps {
  cluster: ecs.Cluster;
  vpc: ec2.IVpc;
}

export class ScotusticianIngestStack extends Stack {
  constructor(scope: Construct, id: string, props: ScotusticianIngestStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    const bucket = s3.Bucket.fromBucketName(this, 'ScotusticianBucket', 'scotustician');

    const image = new ecr_assets.DockerImageAsset(this, 'IngestImage', {
      directory: '../ingest',
    });

    const taskDefinition = new ecs.FargateTaskDefinition(this, 'IngestTaskDef');

    bucket.grantReadWrite(taskDefinition.taskRole);

    const container = taskDefinition.addContainer('IngestContainer', {
      image: ecs.ContainerImage.fromDockerImageAsset(image),
      memoryLimitMiB: 4096,
      cpu: 1024,
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'ingest' }),
      environment: {
        BUCKET_NAME: bucket.bucketName,
      },
    });

    new ecs.FargateService(this, 'IngestService', {
      cluster: props.cluster,
      taskDefinition,
      desiredCount: 1,
    });
  }
}
