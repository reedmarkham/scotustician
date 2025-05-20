import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';

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

    const taskDefinition = new ecs.FargateTaskDefinition(this, 'IngestTaskDef', {
      cpu: 1024,
      memoryLimitMiB: 4096,
    });

    bucket.grantReadWrite(taskDefinition.taskRole);

    taskDefinition.addContainer('IngestContainer', {
      image: ecs.ContainerImage.fromDockerImageAsset(image),
      cpu: 1024,
      memoryLimitMiB: 4096,
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'ingest' }),
      environment: {
        BUCKET_NAME: bucket.bucketName,
      },
    });

    new CfnOutput(this, 'IngestTaskDefinitionArn', {
      value: taskDefinition.taskDefinitionArn,
    });
  }
}
