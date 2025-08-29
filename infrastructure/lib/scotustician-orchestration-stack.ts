import { Construct } from 'constructs';
import * as path from 'path';

import { LogGroup } from 'aws-cdk-lib/aws-logs';
import { PolicyStatement, Effect } from 'aws-cdk-lib/aws-iam';
import { Rule, Schedule, RuleTargetInput } from 'aws-cdk-lib/aws-events';
import { SfnStateMachine } from 'aws-cdk-lib/aws-events-targets';
import { Topic } from 'aws-cdk-lib/aws-sns';
import { Function as LambdaFunction, Runtime, Code } from 'aws-cdk-lib/aws-lambda';
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


export interface ScotusticianOrchestrationStackProps extends StackProps {
  readonly ingestClusterArn: string;
  readonly ingestTaskDefinitionArn: string;
  readonly ingestContainerName: string;
  readonly transformersJobQueueArn: string;
  readonly transformersJobDefinitionArn: string;
  readonly transformersJobName: string;
  readonly clusteringJobQueueArn: string;
  readonly clusteringJobDefinitionArn: string;
  readonly basicClusteringJobName: string;
  readonly termClusteringJobName: string;
  readonly vpcId: string;
  readonly publicSubnetIds: string[];
  readonly privateSubnetIds: string[];
  readonly tsnePerplexity?: string;
  readonly minClusterSize?: string;
  readonly maxConcurrentJobs?: string;
  readonly s3BucketName?: string;
  readonly scheduleEnabled?: boolean;
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

    const dataVerificationFunction = new LambdaFunction(this, 'DataVerificationFunction', {
      runtime: Runtime.PYTHON_3_11,
      handler: 'data_verification.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda')),
      timeout: Duration.minutes(5),
    });

    // IAM policies
    costTrackingFunction.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['ce:GetCostAndUsage'],
      resources: ['*'],
    }));
    this.notificationTopic.grantPublish(costTrackingFunction);

    const bucketName = props.s3BucketName || 'scotustician';
    dataVerificationFunction.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['s3:ListBucket', 's3:GetObject', 'secretsmanager:GetSecretValue'],
      resources: [
        `arn:aws:s3:::${bucketName}`,
        `arn:aws:s3:::${bucketName}/*`,
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
            Name: props.ingestContainerName,
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

    // Exponential backoff polling for ingest completion
    const checkIngestTaskStatus = new CallAwsService(this, 'CheckIngestTaskStatus', {
      service: 'ecs',
      action: 'describeTasks',
      parameters: {
        Cluster: props.ingestClusterArn,
        'Tasks.$': '$.ingestTaskStart.Tasks',
      },
      iamResources: ['*'],
      resultPath: '$.ingestTaskStatus',
    });

    const waitBeforeRetry = new Wait(this, 'WaitBeforeRetry', {
      time: WaitTime.secondsPath('$.waitTime'),
    });

    const incrementRetryCount = new Pass(this, 'IncrementRetryCount', {
      parameters: {
        'retryCount.$': 'States.MathAdd($.retryCount, 1)',
        'waitTime.$': 'States.MathMultiply($.waitTime, 2)',
        'maxRetries': 8,
        'ingestTaskStart.$': '$.ingestTaskStart',
        'inputParams.$': '$.inputParams',
        'costBaseline.$': '$.costBaseline',
      },
    });

    const initializePolling = new Pass(this, 'InitializePolling', {
      parameters: {
        'retryCount': 0,
        'waitTime': 30,
        'maxRetries': 8,
        'ingestTaskStart.$': '$.ingestTaskStart',
        'inputParams.$': '$.inputParams',
        'costBaseline.$': '$.costBaseline',
      },
    });

    // Extract input parameters for dynamic configuration
  const extractInputParams = new Pass(this, 'ExtractInputParams', {
      parameters: {
        'startTerm.$': '$.startTerm',
        'endTerm.$': '$.endTerm',
        'mode.$': '$.mode',
        'executionStartTime.$': '$$.Execution.StartTime'
      },
      resultPath: '$.inputParams'
    });

    const continueAfterIngest = new Pass(this, 'ContinueAfterIngest', {
      comment: 'Continue pipeline after ingest completion'
    });

    // Connect success path from evaluateIngestTaskResult to continue the pipeline
    const ingestSuccess = new Pass(this, 'IngestTaskSuccess', { 
      resultPath: '$.ingestResult' 
    }).next(continueAfterIngest);

    const evaluateIngestTaskResult = new Choice(this, 'EvaluateIngestTaskResult')
      .when(
        Condition.and(
          Condition.stringEquals('$.ingestTaskStatus.Tasks[0].LastStatus', 'STOPPED'),
          Condition.numberEquals('$.ingestTaskStatus.Tasks[0].Containers[0].ExitCode', 0)
        ),
        ingestSuccess
      )
      .when(
        Condition.stringEquals('$.ingestTaskStatus.Tasks[0].LastStatus', 'STOPPED'),
        new Fail(this, 'IngestTaskFailedWithNonZeroExit', {
          causePath: '$.ingestTaskStatus.Tasks[0].Containers[0].Reason',
          error: 'INGEST_TASK_FAILED',
        })
      )
      .when(
        Condition.numberGreaterThanEquals('$.retryCount', 8),
        new Fail(this, 'IngestTaskTimeout', {
          cause: 'Ingest task did not complete within maximum retry attempts',
          error: 'INGEST_TASK_TIMEOUT',
        })
      )
      .when(
        Condition.or(
          Condition.stringEquals('$.ingestTaskStatus.Tasks[0].LastStatus', 'RUNNING'),
          Condition.stringEquals('$.ingestTaskStatus.Tasks[0].LastStatus', 'PENDING')
        ),
        waitBeforeRetry.next(incrementRetryCount)
      )
      .otherwise(
        new Fail(this, 'IngestTaskUnexpectedStatus', {
          causePath: '$.ingestTaskStatus.Tasks[0].LastStatus',
          error: 'INGEST_TASK_UNEXPECTED_STATUS',
        })
      );

    const midPipelineCostCheckTask = new LambdaInvoke(this, 'MidPipelineCostCheck', {
      lambdaFunction: costTrackingFunction,
      payload: TaskInput.fromObject({ stage: 'mid_pipeline', notify: false }),
      resultPath: '$.midPipelineCost',
    });

    const verifyS3DataTask = new LambdaInvoke(this, 'VerifyS3Data', {
      lambdaFunction: dataVerificationFunction,
      payload: TaskInput.fromObject({ type: 's3_ingest', bucket: bucketName, prefix: 'raw/oa/' }),
      resultPath: '$.s3Verification',
    });

  const runEmbeddingsTask = new BatchSubmitJob(this, 'RunEmbeddingsTask', {
      jobName: props.transformersJobName,
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

    const postEmbeddingsCostCheckTask = new LambdaInvoke(this, 'PostEmbeddingsCostCheck', {
      lambdaFunction: costTrackingFunction,
      payload: TaskInput.fromObject({ stage: 'post_embeddings', notify: false }),
      resultPath: '$.postEmbeddingsCost',
    });

  const runBasicClusteringTask = new BatchSubmitJob(this, 'RunBasicClusteringTask', {
      jobName: props.basicClusteringJobName,
      jobQueueArn: props.clusteringJobQueueArn,
      jobDefinitionArn: props.clusteringJobDefinitionArn,
  integrationPattern: IntegrationPattern.RUN_JOB,
      containerOverrides: {
        environment: {
          'S3_BUCKET': bucketName,
          'OUTPUT_PREFIX': 'analysis/case-clustering',
          'TSNE_PERPLEXITY': props.tsnePerplexity || '30',
          'MIN_CLUSTER_SIZE': props.minClusterSize || '5',
          'START_TERM.$': '$.inputParams.startTerm',
          'END_TERM.$': '$.inputParams.endTerm',
        },
      },
      resultPath: '$.basicClusteringResult',
    });

  const runTermByTermClusteringTask = new BatchSubmitJob(this, 'RunTermByTermClusteringTask', {
      jobName: props.termClusteringJobName,
      jobQueueArn: props.clusteringJobQueueArn,
      jobDefinitionArn: props.clusteringJobDefinitionArn,
  integrationPattern: IntegrationPattern.RUN_JOB,
      containerOverrides: {
        environment: {
          'S3_BUCKET': bucketName,
          'BASE_OUTPUT_PREFIX': 'analysis/case-clustering-by-term',
          'TSNE_PERPLEXITY': props.tsnePerplexity || '30',
          'MIN_CLUSTER_SIZE': props.minClusterSize || '5',
          'START_TERM.$': '$.inputParams.startTerm',
          'END_TERM.$': '$.inputParams.endTerm',
          'MAX_CONCURRENT_JOBS': props.maxConcurrentJobs || '3',
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

    const calculateExecutionDuration = new Pass(this, 'CalculateExecutionDuration', {
      parameters: {
        'executionStartTime.$': '$.inputParams.executionStartTime',
        'executionEndTime.$': '$$.State.EnteredTime',
        'durationMinutes.$': 'States.MathAdd(States.MathDiv(States.MathAdd($$.State.EnteredTime, States.MathMultiply($.inputParams.executionStartTime, -1)), 60000), 0)',
        'finalResults.$': '$'
      },
      resultPath: '$.executionMetrics'
    });

    const continueAfterEmbeddings = new Pass(this, 'ContinueAfterEmbeddings', {
      comment: 'Continue pipeline after embeddings verification'
    });

    const continueAfterClustering = new Pass(this, 'ContinueAfterClustering', {
      comment: 'Continue pipeline after clustering completion'
    });

    const s3DataCheck = new Choice(this, 'S3DataCheck')
      .when(Condition.booleanEquals('$.s3Verification.Payload.verified', true), runEmbeddingsTask.next(continueAfterEmbeddings))
      .otherwise(new Fail(this, 'S3VerificationFailed', {
        cause: 'S3 data verification failed',
        error: 'DATA_VERIFICATION_ERROR',
      }));

    const embeddingsDataCheck = new Choice(this, 'EmbeddingsDataCheck')
      .when(Condition.booleanEquals('$.embeddingsVerification.Payload.verified', true), parallelClustering.next(continueAfterClustering))
      .otherwise(new Fail(this, 'EmbeddingsVerificationFailed', {
        cause: 'Embeddings verification failed',
        error: 'DATA_VERIFICATION_ERROR',
      }));

    //
    // Definition
    //
    // Create the polling loop chain
    const pollingChain = checkIngestTaskStatus.next(evaluateIngestTaskResult);
    
    // Connect the retry flow back to the polling chain
    incrementRetryCount.next(pollingChain);

    const definition = extractInputParams
      .next(costBaselineTask)
      .next(startIngestTask)
      .next(initializePolling)
      .next(pollingChain);
    
    // Chain the rest after ingest completion
    continueAfterIngest
      .next(midPipelineCostCheckTask)
      .next(verifyS3DataTask)
      .next(s3DataCheck);
    
    // Chain after embeddings verification 
    continueAfterEmbeddings
      .next(verifyEmbeddingsTask)
      .next(postEmbeddingsCostCheckTask)
      .next(embeddingsDataCheck);
    
    // Chain final steps after clustering
    continueAfterClustering
      .next(finalCostReportTask)
      .next(calculateExecutionDuration);

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
      ],
      resources: [
        props.ingestClusterArn,
        props.ingestTaskDefinitionArn,
        `arn:aws:ecs:${this.region}:${this.account}:task/${props.ingestClusterArn.split('/')[1]}/*`,
      ],
    }));

    this.stateMachine.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: [
        'batch:SubmitJob',
        'batch:DescribeJobs',
        'batch:TerminateJob',
      ],
      resources: [
        props.transformersJobQueueArn,
        props.transformersJobDefinitionArn,
        props.clusteringJobQueueArn,
        props.clusteringJobDefinitionArn,
      ],
    }));

    this.stateMachine.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['iam:PassRole'],
      resources: [
        `arn:aws:iam::${this.account}:role/ecsTaskExecutionRole`,
        `arn:aws:iam::${this.account}:role/*BatchExecutionRole*`,
      ],
    }));

    //
    // Schedule for current year processing during SCOTUS term
    // First Monday in October through Second Friday in July
    //
    if (props.scheduleEnabled !== false) {
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

      new CfnOutput(this, 'ScheduleRuleArn', {
        value: scheduleRule.ruleArn,
        description: 'EventBridge Schedule Rule ARN for current year processing',
      });
    }

    new CfnOutput(this, 'StateMachineArn', {
      value: this.stateMachine.stateMachineArn,
      description: 'Step Functions State Machine ARN',
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
