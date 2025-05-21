import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, RemovalPolicy } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';

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

    // No need for GPU support in the ingest container
    const taskDefinition = new ecs.FargateTaskDefinition(this, 'IngestTaskDef', {
      cpu: 1024,
      memoryLimitMiB: 4096,
    });

    bucket.grantReadWrite(taskDefinition.taskRole);

    const container = taskDefinition.addContainer('IngestContainer', {
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

    new CfnOutput(this, 'IngestContainerName', {
      value: container.containerName,
    });

    const logGroup = new logs.LogGroup(this, 'IngestLogGroup', {
      logGroupName: '/ecs/ingest',
      removalPolicy: RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_WEEK,
    });

    const errorFilter = new logs.MetricFilter(this, 'IngestErrorMetricFilter', {
      logGroup,
      metricName: 'IngestErrors',
      metricNamespace: 'Scotustician',
      filterPattern: logs.FilterPattern.stringValue('$.level', '=', 'ERROR'),
      metricValue: '1',
    });

    new cloudwatch.Alarm(this, 'IngestErrorAlarm', {
      metric: errorFilter.metric(),
      threshold: 1,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Alarm if any ERROR-level logs are detected in the ingest container.',
    });
  }
}
