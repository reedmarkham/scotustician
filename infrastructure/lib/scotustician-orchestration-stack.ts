import { Construct } from 'constructs';
import * as path from 'path';

import { Topic } from 'aws-cdk-lib/aws-sns';
import { LogGroup } from 'aws-cdk-lib/aws-logs';
import { SfnStateMachine } from 'aws-cdk-lib/aws-events-targets';
import { PythonFunction } from '@aws-cdk/aws-lambda-python-alpha';
import {
  Stack, StackProps, DefaultStackSynthesizer, Tags, Duration, CfnOutput
} from 'aws-cdk-lib';
import {
  StateMachine, StateMachineType, TaskInput, Condition, Wait, WaitTime, Pass,
  Choice, Fail, Parallel, IntegrationPattern, LogLevel, DefinitionBody
} from 'aws-cdk-lib/aws-stepfunctions';
import {
  LambdaInvoke, CallAwsService, BatchSubmitJob
} from 'aws-cdk-lib/aws-stepfunctions-tasks';
import {
  Function as LambdaFunction, Runtime, Code
} from 'aws-cdk-lib/aws-lambda';
import {
  PolicyStatement, Effect
} from 'aws-cdk-lib/aws-iam';
import {
  Rule, Schedule, RuleTargetInput
} from 'aws-cdk-lib/aws-events';


export interface ScotusticianOrchestrationStackProps extends StackProps {
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

export class ScotusticianOrchestrationStack extends Stack {
  public readonly stateMachine: StateMachine;
  public readonly notificationTopic: Topic;

  constructor(scope: Construct, id: string, props: ScotusticianOrchestrationStackProps) {
    const qualifier = scope.node.tryGetContext('@aws-cdk:bootstrap-qualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    Tags.of(this).add('Project', 'scotustician');
    Tags.of(this).add('Stack', 'orchestration');

    //
    // Notifications
    //
  this.notificationTopic = new Topic(this, 'PipelineNotifications', {
      topicName: 'scotustician-pipeline-notifications',
      displayName: 'Scotustician Pipeline Notifications',
    });

    //
    // Lambdas
    //
    const costTrackingFunction = new LambdaFunction(this, 'CostTrackingFunction', {
      runtime: Runtime.PYTHON_3_11,
      handler: 'cost_tracking.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda')),
      timeout: Duration.minutes(2),
      environment: {
        SNS_TOPIC_ARN: this.notificationTopic.topicArn,
      },
    });

    const dataVerificationFunction = new PythonFunction(this, 'DataVerificationFunction', {
      runtime: Runtime.PYTHON_3_11,
      handler: 'handler',
      entry: path.join(__dirname, '../lambda'),
      index: 'data_verification.py',
      timeout: Duration.minutes(5),
    });

    // IAM policies
    costTrackingFunction.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['ce:GetCostAndUsage'],
      resources: ['*'],
    }));
    this.notificationTopic.grantPublish(costTrackingFunction);

    dataVerificationFunction.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
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
    const costBaselineTask = new LambdaInvoke(this, 'CostBaseline', {
      lambdaFunction: costTrackingFunction,
      payload: TaskInput.fromObject({ stage: 'baseline', notify: true }),
      resultPath: '$.costBaseline',
    });

  const startIngestTask = new CallAwsService(this, 'StartIngestTask', {
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
    const waitForIngestCompletion = new Wait(this, 'WaitForIngestCompletion', {
      time: WaitTime.duration(Duration.minutes(10)), // Wait 10 minutes for ingest to complete
    });

    // Extract input parameters for dynamic configuration
  const extractInputParams = new Pass(this, 'ExtractInputParams', {
      parameters: {
        'startTerm.$': '$.startTerm',
        'endTerm.$': '$.endTerm',
        'mode.$': '$.mode'
      },
      resultPath: '$.inputParams'
    });

  const checkIngestTaskFinalStatus = new CallAwsService(this, 'CheckIngestTaskFinalStatus', {
      service: 'ecs',
      action: 'describeTasks',
      parameters: {
        Cluster: props.ingestClusterArn,
        'Tasks.$': '$.ingestTaskStart.Tasks',
      },
      iamResources: ['*'],
      resultPath: '$.ingestTaskStatus',
    });

    const evaluateIngestTaskResult = new Choice(this, 'EvaluateIngestTaskResult')
      .when(
        Condition.and(
          Condition.stringEquals('$.ingestTaskStatus.Tasks[0].LastStatus', 'STOPPED'),
          Condition.numberEquals('$.ingestTaskStatus.Tasks[0].Containers[0].ExitCode', 0)
        ),
        new Pass(this, 'IngestTaskSuccess', { resultPath: '$.ingestResult' })
      )
      .when(
        Condition.stringEquals('$.ingestTaskStatus.Tasks[0].LastStatus', 'STOPPED'),
        new Fail(this, 'IngestTaskFailedWithNonZeroExit', {
          causePath: '$.ingestTaskStatus.Tasks[0].Containers[0].Reason',
          error: 'INGEST_TASK_FAILED',
        })
      )
      .when(
        Condition.stringEquals('$.ingestTaskStatus.Tasks[0].LastStatus', 'RUNNING'),
        new Fail(this, 'IngestTaskTimeout', {
          cause: 'Ingest task did not complete within 10 minute timeout',
          error: 'INGEST_TASK_TIMEOUT',
        })
      )
      .otherwise(
        new Fail(this, 'IngestTaskUnexpectedStatus', {
          causePath: '$.ingestTaskStatus.Tasks[0].LastStatus',
          error: 'INGEST_TASK_UNEXPECTED_STATUS',
        })
      );

    const verifyS3DataTask = new LambdaInvoke(this, 'VerifyS3Data', {
      lambdaFunction: dataVerificationFunction,
      payload: TaskInput.fromObject({ type: 's3_ingest', bucket: 'scotustician', prefix: 'raw/oa/' }),
      resultPath: '$.s3Verification',
    });

  const runEmbeddingsTask = new BatchSubmitJob(this, 'RunEmbeddingsTask', {
      jobName: 'scotustician-embeddings-stepfunctions',
      jobQueueArn: props.transformersJobQueueArn,
      jobDefinitionArn: props.transformersJobDefinitionArn,
  integrationPattern: IntegrationPattern.RUN_JOB,
      resultPath: '$.embeddingsResult',
    });

    const verifyEmbeddingsTask = new LambdaInvoke(this, 'VerifyEmbeddings', {
      lambdaFunction: dataVerificationFunction,
      payload: TaskInput.fromObject({ type: 'embeddings' }),
      resultPath: '$.embeddingsVerification',
    });

  const runBasicClusteringTask = new BatchSubmitJob(this, 'RunBasicClusteringTask', {
      jobName: 'scotustician-basic-clustering-stepfunctions',
      jobQueueArn: props.clusteringJobQueueArn,
      jobDefinitionArn: props.clusteringJobDefinitionArn,
  integrationPattern: IntegrationPattern.RUN_JOB,
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

  const runTermByTermClusteringTask = new BatchSubmitJob(this, 'RunTermByTermClusteringTask', {
      jobName: 'scotustician-term-clustering-stepfunctions',
      jobQueueArn: props.clusteringJobQueueArn,
      jobDefinitionArn: props.clusteringJobDefinitionArn,
  integrationPattern: IntegrationPattern.RUN_JOB,
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

  const parallelClustering = new Parallel(this, 'ParallelClustering', {
      resultPath: '$.clusteringResults',
    })
      .branch(runBasicClusteringTask)
      .branch(runTermByTermClusteringTask);

    const finalCostReportTask = new LambdaInvoke(this, 'FinalCostReport', {
      lambdaFunction: costTrackingFunction,
      payload: TaskInput.fromObject({ stage: 'complete', notify: true }),
      resultPath: '$.finalCostReport',
    });

    const s3DataCheck = new Choice(this, 'S3DataCheck')
      .when(Condition.booleanEquals('$.s3Verification.Payload.verified', true), runEmbeddingsTask)
      .otherwise(new Fail(this, 'S3VerificationFailed', {
        cause: 'S3 data verification failed',
        error: 'DATA_VERIFICATION_ERROR',
      }));

    const embeddingsDataCheck = new Choice(this, 'EmbeddingsDataCheck')
      .when(Condition.booleanEquals('$.embeddingsVerification.Payload.verified', true), parallelClustering)
      .otherwise(new Fail(this, 'EmbeddingsVerificationFailed', {
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
    this.stateMachine = new StateMachine(this, 'ScotusticianPipeline', {
      definitionBody: DefinitionBody.fromChainable(definition),
      stateMachineType: StateMachineType.STANDARD,
      timeout: Duration.hours(6),
      logs: {
        destination: LogGroup.fromLogGroupName(this, 'StateMachineLogGroup', '/aws/stepfunctions/scotustician-pipeline'),
        level: LogLevel.ALL,
      },
    });

    this.stateMachine.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
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
    const scheduleRule = new Rule(this, 'CurrentYearScheduleRule', {
      schedule: Schedule.cron({
        minute: '0',
        hour: '14', // 10 AM ET (14:00 UTC)
        weekDay: 'MON,THU',
        month: 'OCT-DEC,JAN-JUL', // Supreme Court term months
      }),
      description: 'Schedule current year data processing twice weekly during SCOTUS term (Oct-Jul)',
    });

    scheduleRule.addTarget(new SfnStateMachine(this.stateMachine, {
      input: RuleTargetInput.fromObject({
        startTerm: currentYear,
        endTerm: currentYear,
        mode: 'scheduled'
      })
    }));

    new CfnOutput(this, 'StateMachineArn', {
      value: this.stateMachine.stateMachineArn,
      description: 'Step Functions State Machine ARN',
    });

    new CfnOutput(this, 'ScheduleRuleArn', {
      value: scheduleRule.ruleArn,
      description: 'EventBridge Schedule Rule ARN for current year processing',
    });

    new CfnOutput(this, 'NotificationTopicArn', {
      value: this.notificationTopic.topicArn,
      description: 'SNS Topic ARN for pipeline notifications',
    });

    new CfnOutput(this, 'StepFunctionsLogGroup', {
      value: '/aws/stepfunctions/scotustician-pipeline',
      description: 'CloudWatch Log Group for Step Functions execution logs',
    });

    new CfnOutput(this, 'StepFunctionsLogGroupConsoleUrl', {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#logsV2:log-groups/log-group/%2Faws%2Fstepfunctions%2Fscotustician-pipeline`,
      description: 'Direct link to Step Functions CloudWatch logs in AWS Console',
    });

    new CfnOutput(this, 'IngestTaskLogGroup', {
      value: '/ecs/scotustician-ingest',
      description: 'CloudWatch Log Group for ECS Ingest Task logs',
    });

    new CfnOutput(this, 'IngestTaskLogGroupConsoleUrl', {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#logsV2:log-groups/log-group/%2Fecs%2Fscotustician-ingest`,
      description: 'Direct link to ECS Ingest Task CloudWatch logs in AWS Console',
    });

    new CfnOutput(this, 'BatchJobLogGroup', {
      value: '/aws/batch/job',
      description: 'CloudWatch Log Group for AWS Batch job logs (transformers/clustering)',
    });

    new CfnOutput(this, 'BatchJobLogGroupConsoleUrl', {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#logsV2:log-groups/log-group/%2Faws%2Fbatch%2Fjob`,
      description: 'Direct link to AWS Batch job CloudWatch logs in AWS Console',
    });
  }
}
