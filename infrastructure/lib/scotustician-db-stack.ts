import { Construct } from 'constructs';
import * as path from 'path';

import { 
  Stack, StackProps, CustomResource, Duration, RemovalPolicy, CfnOutput, DefaultStackSynthesizer 
} from 'aws-cdk-lib';
import { IBucket } from 'aws-cdk-lib/aws-s3';
import { 
  Vpc, SecurityGroup, Peer, Port, SubnetType, GatewayVpcEndpoint, InterfaceVpcEndpoint, GatewayVpcEndpointAwsService, 
  InterfaceVpcEndpointAwsService, InstanceType, InstanceClass, InstanceSize 
} from 'aws-cdk-lib/aws-ec2';
import { 
  DatabaseInstance, DatabaseInstanceEngine, PostgresEngineVersion, SubnetGroup, Credentials, StorageType, ParameterGroup 
} from 'aws-cdk-lib/aws-rds';
import { Function as LambdaFunction, Runtime, Code } from 'aws-cdk-lib/aws-lambda';
import { Provider } from 'aws-cdk-lib/custom-resources';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { 
  Role, ServicePrincipal, ManagedPolicy, PolicyDocument, PolicyStatement, ArnPrincipal, Effect
} from 'aws-cdk-lib/aws-iam';
import { CfnResourcePolicy } from 'aws-cdk-lib/aws-secretsmanager';
import { 
  Cluster, FargateTaskDefinition, ContainerImage, LogDrivers, Secret as EcsSecret, FargatePlatformVersion, ContainerInsights 
} from 'aws-cdk-lib/aws-ecs';
import { Rule, Schedule } from 'aws-cdk-lib/aws-events';
import { EcsTask } from 'aws-cdk-lib/aws-events-targets';
import { DockerImageAsset, Platform } from 'aws-cdk-lib/aws-ecr-assets';


export interface ScotusticianDbStackProps extends StackProps {
  awsIamArn: string;
  scotusticianBucket: IBucket;
}

export class ScotusticianDbStack extends Stack {
  constructor(scope: Construct, id: string, props: ScotusticianDbStackProps) {
    const qualifier = scope.node.tryGetContext('@aws-cdk:bootstrap-qualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    const scotusticianUserArn = props.awsIamArn;
    if (!scotusticianUserArn) {
      throw new Error('awsIamArn prop must be defined');
    }

    const scotusticianBucket = props.scotusticianBucket;

    // const scotusticianBucket = new s3.Bucket(this, 'ScotusticianBucket', {
    //   bucketName: 'scotustician',
    //   removalPolicy: cdk.RemovalPolicy.RETAIN,
    //   encryption: s3.BucketEncryption.S3_MANAGED,
    //   blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    // });

  const vpc = new Vpc(this, 'ScotusticianVpc', {
      maxAzs: 2,
      natGateways: 0, // Cost optimization: no NAT gateways
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: 'isolated-subnet',
          subnetType: SubnetType.PRIVATE_ISOLATED,
        },
      ],
    });

  const dbSecurityGroup = new SecurityGroup(this, 'ScotusticianDbSecurityGroup', {
      vpc,
      description: 'Security group for Scotustician RDS instance - restricted access',
      allowAllOutbound: false,
    });

    // Only allow access from within VPC CIDR range
    dbSecurityGroup.addIngressRule(
      Peer.ipv4(vpc.vpcCidrBlock),
      Port.tcp(5432),
      'Allow PostgreSQL access from VPC only'
    );

  const subnetGroup = new SubnetGroup(this, 'ScotusticianDbSubnetGroup', {
      vpc,
      description: 'Subnet group for Scotustician RDS instance',
      vpcSubnets: {
  subnetType: SubnetType.PRIVATE_ISOLATED,
      },
    });

    const postgresInstance = new DatabaseInstance(this, 'ScotusticianPostgresInstance', {
      engine: DatabaseInstanceEngine.postgres({
        version: PostgresEngineVersion.VER_16,
      }),
  instanceType: InstanceType.of(InstanceClass.T3, InstanceSize.MICRO), // Cost-effective
      vpc,
      subnetGroup,
      securityGroups: [dbSecurityGroup],
      databaseName: 'scotustician',
      credentials: Credentials.fromGeneratedSecret('dbuser', {
        secretName: 'scotustician-db-credentials',
      }),
      allocatedStorage: 20,
      storageType: StorageType.GP2,
      backupRetention: Duration.days(7),
      deletionProtection: false,
      removalPolicy: RemovalPolicy.RETAIN,
      storageEncrypted: true,
      publiclyAccessible: false, // Security: no public access
      parameterGroup: new ParameterGroup(this, 'ScotusticianDbParameterGroup', {
        engine: DatabaseInstanceEngine.postgres({
          version: PostgresEngineVersion.VER_16,
        }),
        parameters: {
          // Common performance-related parameters for PostgreSQL
          'shared_preload_libraries': 'pg_stat_statements',
          'pg_stat_statements.track': 'all',
          'log_statement': 'all',
          'log_duration': 'on',
        },
      }),
    });

    // VPC Endpoints for AWS services
  const secretsManagerEndpoint = new InterfaceVpcEndpoint(this, 'SecretsManagerVpcEndpoint', {
      vpc,
      service: InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
      subnets: {
  subnetType: SubnetType.PRIVATE_ISOLATED,
      },
    });

  const s3Endpoint = new GatewayVpcEndpoint(this, 'S3VpcEndpoint', {
      vpc,
      service: GatewayVpcEndpointAwsService.S3,
      subnets: [{
  subnetType: SubnetType.PRIVATE_ISOLATED,
      }],
    });

    // Lambda function for database initialization
    const dbInitFunction = new LambdaFunction(this, 'DbInitFunction', {
      runtime: Runtime.PYTHON_3_11,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda'), {
        bundling: {
          image: Runtime.PYTHON_3_11.bundlingImage,
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output'
          ],
        },
      }),
      vpc,
      vpcSubnets: {
  subnetType: SubnetType.PRIVATE_ISOLATED,
      },
      securityGroups: [dbSecurityGroup],
      timeout: Duration.minutes(5),
      environment: {
        AWS_NODEJS_CONNECTION_REUSE_ENABLED: '1',
      },
      logGroup: new LogGroup(this, 'DbInitFunctionLogGroup', {
        retention: RetentionDays.ONE_WEEK,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
    });

    // Grant permissions to Lambda function
    postgresInstance.secret!.grantRead(dbInitFunction);

    // Add resource policy to restrict secret access to specific IAM user only
    const secretResourcePolicy = new PolicyDocument({
      statements: [
        new PolicyStatement({
          sid: 'AllowScotusticianUserAccess',
          effect: Effect.ALLOW,
          principals: [new ArnPrincipal(scotusticianUserArn)],
          actions: [
            'secretsmanager:GetSecretValue',
            'secretsmanager:DescribeSecret'
          ],
          resources: ['*'],
        }),
        new PolicyStatement({
          sid: 'AllowLambdaInitAccess',
          effect: Effect.ALLOW,
          principals: [new ArnPrincipal(dbInitFunction.role!.roleArn)],
          actions: [
            'secretsmanager:GetSecretValue',
            'secretsmanager:DescribeSecret'
          ],
          resources: ['*'],
        }),
      ],
    });

    // Create a separate resource policy for the database secret
    new CfnResourcePolicy(this, 'DbSecretResourcePolicy', {
      secretId: postgresInstance.secret!.secretArn,
      resourcePolicy: secretResourcePolicy.toJSON(),
    });
    
    // Allow Lambda to connect to RDS
    dbSecurityGroup.addIngressRule(
      dbSecurityGroup,
      Port.tcp(5432),
      'Allow Lambda to connect to RDS'
    );

    // Allow Lambda to connect to RDS PostgreSQL
    dbSecurityGroup.addEgressRule(
      dbSecurityGroup,
      Port.tcp(5432),
      'Allow Lambda to connect to RDS'
    );

    // Allow Lambda to access VPC endpoints for AWS services
    dbSecurityGroup.addEgressRule(
      Peer.ipv4(vpc.vpcCidrBlock),
      Port.tcp(443),
      'Allow HTTPS access to VPC endpoints'
    );

    // Custom resource to trigger database initialization
    const dbInitProvider = new Provider(this, 'DbInitProvider', {
      onEventHandler: dbInitFunction,
      logGroup: new LogGroup(this, 'DbInitProviderLogGroup', {
        retention: RetentionDays.ONE_WEEK,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
    });

    const dbInitResource = new CustomResource(this, 'DbInitResource', {
      serviceToken: dbInitProvider.serviceToken,
      properties: {
        SecretArn: postgresInstance.secret!.secretArn,
        DbEndpoint: postgresInstance.instanceEndpoint.hostname,
        DbPort: postgresInstance.instanceEndpoint.port.toString(),
        DbName: 'scotustician',
        // Add a timestamp to force update on stack updates
        Timestamp: new Date().toISOString(),
      },
    });

    // Ensure database is ready before initialization
    dbInitResource.node.addDependency(postgresInstance);

    // ========================================
    // ECS Fargate Infrastructure for dbt
    // ========================================

    // Create ECS Cluster
  const ecsCluster = new Cluster(this, 'DbtEcsCluster', {
      vpc,
      clusterName: 'scotustician-dbt-cluster',
      containerInsightsV2: ContainerInsights.ENABLED,
    });

    // Create CloudWatch Log Group for dbt
    const dbtLogGroup = new LogGroup(this, 'DbtLogGroup', {
      logGroupName: '/ecs/scotustician-dbt',
      retention: RetentionDays.ONE_WEEK,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // Create ECS Task Execution Role
    const dbtTaskExecutionRole = new Role(this, 'DbtTaskExecutionRole', {
      assumedBy: new ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    // Create ECS Task Role
    const dbtTaskRole = new Role(this, 'DbtTaskRole', {
      assumedBy: new ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    // Grant the task role access to the database secret
    postgresInstance.secret!.grantRead(dbtTaskRole);
    
    // Grant the task role access to S3 bucket for dbt artifacts
    scotusticianBucket.grantReadWrite(dbtTaskRole);

    // Create dbt Docker image asset
    const dbtImage = new DockerImageAsset(this, 'DbtImage', {
      directory: path.join(__dirname, '../../database/dbt'),
      platform: Platform.LINUX_AMD64,
    });

    // Create Task Definition for dbt
    const dbtTaskDefinition = new FargateTaskDefinition(this, 'DbtTaskDefinition', {
      family: 'scotustician-dbt-task',
      memoryLimitMiB: 2048,
      cpu: 1024,
      executionRole: dbtTaskExecutionRole,
      taskRole: dbtTaskRole,
    });

    // Add container to task definition
    dbtTaskDefinition.addContainer('dbt-container', {
      image: ContainerImage.fromDockerImageAsset(dbtImage),
      logging: LogDrivers.awsLogs({
        streamPrefix: 'dbt',
        logGroup: dbtLogGroup,
      }),
      environment: {
        DBT_TARGET: 'prod',
        AWS_DEFAULT_REGION: this.region,
        S3_BUCKET: scotusticianBucket.bucketName,
      },
      secrets: {
        DB_HOST: EcsSecret.fromSecretsManager(postgresInstance.secret!, 'host'),
        DB_PORT: EcsSecret.fromSecretsManager(postgresInstance.secret!, 'port'),
        DB_NAME: EcsSecret.fromSecretsManager(postgresInstance.secret!, 'dbname'),
        DB_USER: EcsSecret.fromSecretsManager(postgresInstance.secret!, 'username'),
        DB_PASSWORD: EcsSecret.fromSecretsManager(postgresInstance.secret!, 'password'),
      },
    });

    // Create Security Group for ECS Tasks
    const dbtSecurityGroup = new SecurityGroup(this, 'DbtEcsSecurityGroup', {
      vpc,
      description: 'Security group for dbt ECS tasks',
      allowAllOutbound: false,
    });

    // Allow ECS tasks to connect to RDS
    dbtSecurityGroup.addEgressRule(
      dbSecurityGroup,
      Port.tcp(5432),
      'Allow dbt to connect to RDS'
    );

    // Allow RDS to accept connections from ECS tasks
    dbSecurityGroup.addIngressRule(
      dbtSecurityGroup,
      Port.tcp(5432),
      'Allow dbt ECS tasks to connect'
    );

    // Allow ECS tasks to access VPC endpoints
    dbtSecurityGroup.addEgressRule(
      Peer.ipv4(vpc.vpcCidrBlock),
      Port.tcp(443),
      'Allow HTTPS access to VPC endpoints'
    );

    // Create EventBridge rule for scheduled dbt runs
    const dbtScheduleRule = new Rule(this, 'DbtScheduleRule', {
      ruleName: 'scotustician-dbt-schedule',
      description: 'Trigger dbt runs weekly on Sunday at 12 PM ET',
      schedule: Schedule.cron({
        minute: '0',
        hour: '17',  // 12 PM ET = 5 PM UTC (4 PM during DST)
        weekDay: 'SUN',
      }),
    });

    // Add ECS task as target for the EventBridge rule
    dbtScheduleRule.addTarget(
      new EcsTask({
        cluster: ecsCluster,
        taskDefinition: dbtTaskDefinition,
        taskCount: 1,
        subnetSelection: {
    subnetType: SubnetType.PRIVATE_ISOLATED,
        },
        securityGroups: [dbtSecurityGroup],
        platformVersion: FargatePlatformVersion.LATEST,
      })
    );

    // Create a Lambda function to trigger dbt runs manually
    const dbtTriggerFunction = new LambdaFunction(this, 'DbtTriggerFunction', {
      runtime: Runtime.PYTHON_3_11,
      handler: 'index.handler',
      code: Code.fromInline(`
import boto3
import json
import os

def handler(event, context):
    ecs_client = boto3.client('ecs')
    
    # Parse dbt command from event
    dbt_command = event.get('dbt_command', 'dbt run')
    
    response = ecs_client.run_task(
        cluster=os.environ['CLUSTER_NAME'],
        taskDefinition=os.environ['TASK_DEFINITION'],
        launchType='FARGATE',
        networkConfiguration={
            'awsvpcConfiguration': {
                'subnets': json.loads(os.environ['SUBNET_IDS']),
                'securityGroups': [os.environ['SECURITY_GROUP_ID']],
                'assignPublicIp': 'DISABLED'
            }
        },
        overrides={
            'containerOverrides': [
                {
                    'name': 'dbt-container',
                    'command': dbt_command.split()
                }
            ]
        }
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'taskArn': response['tasks'][0]['taskArn'] if response['tasks'] else None,
            'command': dbt_command
        })
    }
      `),
      environment: {
        CLUSTER_NAME: ecsCluster.clusterName,
        TASK_DEFINITION: dbtTaskDefinition.taskDefinitionArn,
  SUBNET_IDS: JSON.stringify(vpc.selectSubnets({ subnetType: SubnetType.PRIVATE_ISOLATED }).subnetIds),
        SECURITY_GROUP_ID: dbtSecurityGroup.securityGroupId,
      },
  timeout: Duration.seconds(30),
    });

    // Grant Lambda permission to run ECS tasks
    dbtTriggerFunction.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: [
        'ecs:RunTask',
      ],
      resources: [dbtTaskDefinition.taskDefinitionArn],
    }));

    dbtTriggerFunction.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: [
        'iam:PassRole',
      ],
      resources: [
        dbtTaskExecutionRole.roleArn,
        dbtTaskRole.roleArn,
      ],
    }));

    // Outputs
    new CfnOutput(this, 'DatabaseEndpoint', {
      value: postgresInstance.instanceEndpoint.hostname,
      description: 'RDS Postgres instance endpoint (VPC access only)',
    });

    new CfnOutput(this, 'DatabasePort', {
      value: postgresInstance.instanceEndpoint.port.toString(),
      description: 'RDS Postgres instance port',
    });

    new CfnOutput(this, 'VpcId', {
      value: vpc.vpcId,
      description: 'VPC ID for database access',
    });

    new CfnOutput(this, 'SecretArn', {
      value: postgresInstance.secret!.secretArn,
      description: 'ARN of the database credentials secret',
    });

    new CfnOutput(this, 'DbInitStatus', {
      value: 'Database initialization will run automatically after deployment',
      description: 'Database initialization status',
    });

    new CfnOutput(this, 'EcsClusterName', {
      value: ecsCluster.clusterName,
      description: 'ECS Cluster name for dbt',
    });

    new CfnOutput(this, 'DbtTaskDefinitionArn', {
      value: dbtTaskDefinition.taskDefinitionArn,
      description: 'dbt Task Definition ARN',
    });

    new CfnOutput(this, 'DbtTriggerFunctionName', {
      value: dbtTriggerFunction.functionName,
      description: 'Lambda function name to trigger dbt runs',
    });
  }
}
