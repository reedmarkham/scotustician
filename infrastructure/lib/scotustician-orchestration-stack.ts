import * as cdk from 'aws-cdk-lib';
import * as stepfunctions from 'aws-cdk-lib/aws-stepfunctions';
import * as stepfunctionstasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as path from 'path';
import { PythonFunction } from '@aws-cdk/aws-lambda-python-alpha';
import { Construct } from 'constructs';

export interface ScotusticianOrchestrationStackProps extends cdk.StackProps {
  readonly ingestClusterArn: string;
  readonly ingestTaskDefinitionArn: string;
  readonly transformersJobQueueArn: string;
  readonly transformersJobDefinitionArn: string;
  readonly clusteringJobQueueArn: string;
  readonly clusteringJobDefinitionArn: string;
  readonly vpcId: string;
  readonly publicSubnetIds: string[];
  readonly privateSubnetIds: string[];
}

export class ScotusticianOrchestrationStack extends cdk.Stack {
  public readonly stateMachine: stepfunctions.StateMachine;
  public readonly notificationTopic: sns.Topic;

  constructor(scope: Construct, id: string, props: ScotusticianOrchestrationStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
    });

    cdk.Tags.of(this).add('Project', 'scotustician');
    cdk.Tags.of(this).add('Stack', 'orchestration');

    //
    // Notifications
    //
    this.notificationTopic = new sns.Topic(this, 'PipelineNotifications', {
      topicName: 'scotustician-pipeline-notifications',
      displayName: 'Scotustician Pipeline Notifications',
    });

    //
    // Lambdas
    //
    const costTrackingFunction = new lambda.Function(this, 'CostTrackingFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'cost_tracking.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda')),
      timeout: cdk.Duration.minutes(2),
      environment: {
        SNS_TOPIC_ARN: this.notificationTopic.topicArn,
      },
    });

    const dataVerificationFunction = new PythonFunction(this, 'DataVerificationFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'handler',
      entry: path.join(__dirname, '../lambda'),
      index: 'data_verification.py',
      timeout: cdk.Duration.minutes(5),
    });

    // IAM policies
    costTrackingFunction.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['ce:GetCostAndUsage'],
      resources: ['*'],
    }));
    this.notificationTopic.grantPublish(costTrackingFunction);

    dataVerificationFunction.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['s3:ListBucket', 's3:GetObject', 'secretsmanager:GetSecretValue'],
      resources: [
        'arn:aws:s3:::scotustician',
        'arn:aws:s3:::scotustician/*',
        `arn:aws:secretsmanager:${this.region}:${this.account}:secret:scotustician-db-credentials*`,
      ],
    }));

    //
    // Step Function Tasks
    //
    const costBaselineTask = new stepfunctionstasks.LambdaInvoke(this, 'CostBaseline', {
      lambdaFunction: costTrackingFunction,
      payload: stepfunctions.TaskInput.fromObject({ stage: 'baseline', notify: true }),
      resultPath: '$.costBaseline',
    });

    const startIngestTask = new stepfunctionstasks.CallAwsService(this, 'StartIngestTask', {
      service: 'ecs',
      action: 'runTask',
      parameters: {
        Cluster: props.ingestClusterArn,
        TaskDefinition: props.ingestTaskDefinitionArn,
        LaunchType: 'FARGATE',
        NetworkConfiguration: {
          AwsvpcConfiguration: {
            Subnets: props.publicSubnetIds,
            AssignPublicIp: 'ENABLED',
          },
        },
        Overrides: {
          ContainerOverrides: [{
            Name: 'IngestContainer',
            Environment: [
              {
                Name: 'START_TERM',
                'Value.$': '$.inputParams.startTerm'
              },
              {
                Name: 'END_TERM', 
                'Value.$': '$.inputParams.endTerm'
              }
            ]
          }]
        }
      },
      iamResources: ['*'],
      resultPath: '$.ingestTaskStart',
    });

    // Use a simpler approach - wait a fixed time and then check status once
    const waitForIngestCompletion = new stepfunctions.Wait(this, 'WaitForIngestCompletion', {
      time: stepfunctions.WaitTime.duration(cdk.Duration.minutes(10)), // Wait 10 minutes for ingest to complete
    });

    // Extract input parameters for dynamic configuration
    const extractInputParams = new stepfunctions.Pass(this, 'ExtractInputParams', {
      parameters: {
        'startTerm.$': '$.startTerm',
        'endTerm.$': '$.endTerm',
        'mode.$': '$.mode'
      },
      resultPath: '$.inputParams'
    });

    const checkIngestTaskFinalStatus = new stepfunctionstasks.CallAwsService(this, 'CheckIngestTaskFinalStatus', {
      service: 'ecs',
      action: 'describeTasks',
      parameters: {
        Cluster: props.ingestClusterArn,
        'Tasks.$': '$.ingestTaskStart.Tasks[0].TaskArn',
      },
      iamResources: ['*'],
      resultPath: '$.ingestTaskStatus',
    });

    const evaluateIngestTaskResult = new stepfunctions.Choice(this, 'EvaluateIngestTaskResult')
      .when(
        stepfunctions.Condition.and(
          stepfunctions.Condition.stringEquals('$.ingestTaskStatus.Tasks[0].LastStatus', 'STOPPED'),
          stepfunctions.Condition.numberEquals('$.ingestTaskStatus.Tasks[0].Containers[0].ExitCode', 0)
        ),
        new stepfunctions.Pass(this, 'IngestTaskSuccess', { resultPath: '$.ingestResult' })
      )
      .when(
        stepfunctions.Condition.stringEquals('$.ingestTaskStatus.Tasks[0].LastStatus', 'STOPPED'),
        new stepfunctions.Fail(this, 'IngestTaskFailedWithNonZeroExit', {
          causePath: '$.ingestTaskStatus.Tasks[0].Containers[0].Reason',
          error: 'INGEST_TASK_FAILED',
        })
      )
      .when(
        stepfunctions.Condition.stringEquals('$.ingestTaskStatus.Tasks[0].LastStatus', 'RUNNING'),
        new stepfunctions.Fail(this, 'IngestTaskTimeout', {
          cause: 'Ingest task did not complete within 10 minute timeout',
          error: 'INGEST_TASK_TIMEOUT',
        })
      )
      .otherwise(
        new stepfunctions.Fail(this, 'IngestTaskUnexpectedStatus', {
          causePath: '$.ingestTaskStatus.Tasks[0].LastStatus',
          error: 'INGEST_TASK_UNEXPECTED_STATUS',
        })
      );

    const verifyS3DataTask = new stepfunctionstasks.LambdaInvoke(this, 'VerifyS3Data', {
      lambdaFunction: dataVerificationFunction,
      payload: stepfunctions.TaskInput.fromObject({ type: 's3_ingest', bucket: 'scotustician', prefix: 'raw/oa/' }),
      resultPath: '$.s3Verification',
    });

    const runEmbeddingsTask = new stepfunctionstasks.BatchSubmitJob(this, 'RunEmbeddingsTask', {
      jobName: 'scotustician-embeddings-stepfunctions',
      jobQueueArn: props.transformersJobQueueArn,
      jobDefinitionArn: props.transformersJobDefinitionArn,
      integrationPattern: stepfunctions.IntegrationPattern.RUN_JOB,
      resultPath: '$.embeddingsResult',
    });

    const verifyEmbeddingsTask = new stepfunctionstasks.LambdaInvoke(this, 'VerifyEmbeddings', {
      lambdaFunction: dataVerificationFunction,
      payload: stepfunctions.TaskInput.fromObject({ type: 'embeddings' }),
      resultPath: '$.embeddingsVerification',
    });

    const runBasicClusteringTask = new stepfunctionstasks.BatchSubmitJob(this, 'RunBasicClusteringTask', {
      jobName: 'scotustician-basic-clustering-stepfunctions',
      jobQueueArn: props.clusteringJobQueueArn,
      jobDefinitionArn: props.clusteringJobDefinitionArn,
      integrationPattern: stepfunctions.IntegrationPattern.RUN_JOB,
      containerOverrides: {
        environment: {
          'S3_BUCKET': 'scotustician',
          'OUTPUT_PREFIX': 'analysis/case-clustering',
          'TSNE_PERPLEXITY': '30',
          'MIN_CLUSTER_SIZE': '5',
          'START_TERM.$': '$.inputParams.startTerm',
          'END_TERM.$': '$.inputParams.endTerm',
        },
      },
      resultPath: '$.basicClusteringResult',
    });

    const runTermByTermClusteringTask = new stepfunctionstasks.BatchSubmitJob(this, 'RunTermByTermClusteringTask', {
      jobName: 'scotustician-term-clustering-stepfunctions',
      jobQueueArn: props.clusteringJobQueueArn,
      jobDefinitionArn: props.clusteringJobDefinitionArn,
      integrationPattern: stepfunctions.IntegrationPattern.RUN_JOB,
      containerOverrides: {
        environment: {
          'S3_BUCKET': 'scotustician',
          'BASE_OUTPUT_PREFIX': 'analysis/case-clustering-by-term',
          'TSNE_PERPLEXITY': '30',
          'MIN_CLUSTER_SIZE': '5',
          'START_TERM.$': '$.inputParams.startTerm',
          'END_TERM.$': '$.inputParams.endTerm',
          'MAX_CONCURRENT_JOBS': '3',
        },
      },
      resultPath: '$.termByTermClusteringResult',
    });

    const parallelClustering = new stepfunctions.Parallel(this, 'ParallelClustering', {
      resultPath: '$.clusteringResults',
    })
      .branch(runBasicClusteringTask)
      .branch(runTermByTermClusteringTask);

    const finalCostReportTask = new stepfunctionstasks.LambdaInvoke(this, 'FinalCostReport', {
      lambdaFunction: costTrackingFunction,
      payload: stepfunctions.TaskInput.fromObject({ stage: 'complete', notify: true }),
      resultPath: '$.finalCostReport',
    });

    const s3DataCheck = new stepfunctions.Choice(this, 'S3DataCheck')
      .when(stepfunctions.Condition.booleanEquals('$.s3Verification.Payload.verified', true), runEmbeddingsTask)
      .otherwise(new stepfunctions.Fail(this, 'S3VerificationFailed', {
        cause: 'S3 data verification failed',
        error: 'DATA_VERIFICATION_ERROR',
      }));

    const embeddingsDataCheck = new stepfunctions.Choice(this, 'EmbeddingsDataCheck')
      .when(stepfunctions.Condition.booleanEquals('$.embeddingsVerification.Payload.verified', true), parallelClustering)
      .otherwise(new stepfunctions.Fail(this, 'EmbeddingsVerificationFailed', {
        cause: 'Embeddings verification failed',
        error: 'DATA_VERIFICATION_ERROR',
      }));

    //
    // Definition
    //
    const definition = extractInputParams
      .next(costBaselineTask)
      .next(startIngestTask)
      .next(waitForIngestCompletion)
      .next(checkIngestTaskFinalStatus)
      .next(evaluateIngestTaskResult.afterwards()
        .next(verifyS3DataTask)
        .next(s3DataCheck.afterwards()
          .next(verifyEmbeddingsTask)
          .next(embeddingsDataCheck.afterwards()
            .next(finalCostReportTask))));

    //
    // State Machine
    //
    this.stateMachine = new stepfunctions.StateMachine(this, 'ScotusticianPipeline', {
      definition,
      stateMachineType: stepfunctions.StateMachineType.STANDARD,
      timeout: cdk.Duration.hours(6),
      logs: {
        destination: logs.LogGroup.fromLogGroupName(this, 'StateMachineLogGroup', '/aws/stepfunctions/scotustician-pipeline'),
        level: stepfunctions.LogLevel.ALL,
      },
    });

    this.stateMachine.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ecs:RunTask',
        'ecs:DescribeTasks',
        'ecs:StopTask',
        'batch:SubmitJob',
        'batch:DescribeJobs',
        'batch:TerminateJob',
        'iam:PassRole',
      ],
      resources: ['*'],
    }));

    //
    // Schedule for current year processing during SCOTUS term
    // First Monday in October through Second Friday in July
    //
    const currentYear = new Date().getFullYear().toString();
    const scheduleRule = new events.Rule(this, 'CurrentYearScheduleRule', {
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '14', // 10 AM ET (14:00 UTC)
        weekDay: 'MON,THU',
        month: 'OCT-DEC,JAN-JUL', // Supreme Court term months
      }),
      description: 'Schedule current year data processing twice weekly during SCOTUS term (Oct-Jul)',
    });

    scheduleRule.addTarget(new targets.SfnStateMachine(this.stateMachine, {
      input: events.RuleTargetInput.fromObject({
        startTerm: currentYear,
        endTerm: currentYear,
        mode: 'scheduled'
      })
    }));

    new cdk.CfnOutput(this, 'StateMachineArn', {
      value: this.stateMachine.stateMachineArn,
      description: 'Step Functions State Machine ARN',
    });

    new cdk.CfnOutput(this, 'ScheduleRuleArn', {
      value: scheduleRule.ruleArn,
      description: 'EventBridge Schedule Rule ARN for current year processing',
    });

    new cdk.CfnOutput(this, 'NotificationTopicArn', {
      value: this.notificationTopic.topicArn,
      description: 'SNS Topic ARN for pipeline notifications',
    });

    new cdk.CfnOutput(this, 'StepFunctionsLogGroup', {
      value: '/aws/stepfunctions/scotustician-pipeline',
      description: 'CloudWatch Log Group for Step Functions execution logs',
    });

    new cdk.CfnOutput(this, 'StepFunctionsLogGroupConsoleUrl', {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#logsV2:log-groups/log-group/%2Faws%2Fstepfunctions%2Fscotustician-pipeline`,
      description: 'Direct link to Step Functions CloudWatch logs in AWS Console',
    });

    new cdk.CfnOutput(this, 'IngestTaskLogGroup', {
      value: '/ecs/scotustician-ingest',
      description: 'CloudWatch Log Group for ECS Ingest Task logs',
    });

    new cdk.CfnOutput(this, 'IngestTaskLogGroupConsoleUrl', {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#logsV2:log-groups/log-group/%2Fecs%2Fscotustician-ingest`,
      description: 'Direct link to ECS Ingest Task CloudWatch logs in AWS Console',
    });

    new cdk.CfnOutput(this, 'BatchJobLogGroup', {
      value: '/aws/batch/job',
      description: 'CloudWatch Log Group for AWS Batch job logs (transformers/clustering)',
    });

    new cdk.CfnOutput(this, 'BatchJobLogGroupConsoleUrl', {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#logsV2:log-groups/log-group/%2Faws%2Fbatch%2Fjob`,
      description: 'Direct link to AWS Batch job CloudWatch logs in AWS Console',
    });
  }
}
