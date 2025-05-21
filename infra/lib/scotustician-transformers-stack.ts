import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, RemovalPolicy } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';

export interface ScotusticianTransformersStackProps extends StackProps {
  vpc: ec2.IVpc;
  cluster: ecs.Cluster;
}

export class ScotusticianTransformersStack extends Stack {
  constructor(scope: Construct, id: string, props: ScotusticianTransformersStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';
    const useGpu = scope.node.tryGetContext('useGpu') === 'true';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    const image = new ecr_assets.DockerImageAsset(this, 'TransformersImage', {
      directory: '../transformers',
    });

    let taskDefinition: ecs.TaskDefinition;
    let container: ecs.ContainerDefinition;

    if (useGpu) {
      taskDefinition = new ecs.Ec2TaskDefinition(this, 'TransformersGpuTaskDef', {
        networkMode: ecs.NetworkMode.AWS_VPC,
      });

      container = taskDefinition.addContainer('TransformersGpuContainer', {
        image: ecs.ContainerImage.fromDockerImageAsset(image),
        memoryLimitMiB: 6144,
        cpu: 512,
        gpuCount: 1,
        logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'transformers' }),
        environment: {
          OPENSEARCH_HOST: process.env.OPENSEARCH_HOST || 'https://scotusticianope-x0u0hjgyswq0.us-east-1.es.amazonaws.com',
          S3_BUCKET: 'scotustician',
          MAX_WORKERS: '1',
        },
        command: ['python', 'batch_embed.py'],
      });
    } else {
      const fargateTask = new ecs.FargateTaskDefinition(this, 'TransformersCpuTaskDef', {
        cpu: 4096,
        memoryLimitMiB: 8192,
      });
      taskDefinition = fargateTask;

      container = fargateTask.addContainer('TransformersCpuContainer', {
        image: ecs.ContainerImage.fromDockerImageAsset(image),
        logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'transformers' }),
        environment: {
          OPENSEARCH_HOST: process.env.OPENSEARCH_HOST || 'https://scotusticianope-x0u0hjgyswq0.us-east-1.es.amazonaws.com',
          S3_BUCKET: 'scotustician',
          MAX_WORKERS: '1',
        },
        command: ['python', 'batch_embed.py'],
      });
    }

    container.addUlimits({
      name: ecs.UlimitName.NOFILE,
      softLimit: 65536,
      hardLimit: 65536,
    });

    taskDefinition.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['es:ESHttpPost', 'es:ESHttpPut', 'es:ESHttpGet', 'es:ESHttpHead'],
      resources: [`arn:aws:es:us-east-1:${this.account}:domain/scotusticianope-x0u0hjgyswq0/*`],
    }));

    taskDefinition.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject', 's3:ListBucket', 's3:PutObject'],
      resources: ['arn:aws:s3:::scotustician', 'arn:aws:s3:::scotustician/*'],
    }));

    taskDefinition.addToExecutionRolePolicy(new iam.PolicyStatement({
      actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
      resources: ['*'],
    }));

    new CfnOutput(this, useGpu ? 'TransformersGpuTaskDefinitionArn' : 'TransformersCpuTaskDefinitionArn', {
      value: taskDefinition.taskDefinitionArn,
    });

    new CfnOutput(this, useGpu ? 'TransformersGpuContainerName' : 'TransformersCpuContainerName', {
      value: container.containerName,
    });

    const logGroup = new logs.LogGroup(this, 'TransformersLogGroup', {
      logGroupName: '/ecs/transformers',
      removalPolicy: RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_WEEK,
    });

    const errorFilter = new logs.MetricFilter(this, 'ErrorMetricFilter', {
      logGroup,
      metricName: 'TransformerErrors',
      metricNamespace: 'Scotustician',
      filterPattern: logs.FilterPattern.stringValue('$.level', '=', 'ERROR'),
      metricValue: '1',
    });

    new cloudwatch.Alarm(this, 'TransformerErrorAlarm', {
      metric: errorFilter.metric(),
      threshold: 1,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Alarm if any ERROR-level logs are detected in the transformers container.',
    });
  }
}