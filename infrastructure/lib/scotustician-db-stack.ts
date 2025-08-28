import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import { DefaultStackSynthesizer } from 'aws-cdk-lib';
import * as path from 'path';

export class ScotusticianDbStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    const scotusticianUserArn = this.node.tryGetContext('awsIamArn');
    if (!scotusticianUserArn) {
      throw new Error('Environment variable AWS_IAM_ARN must be defined');
    }

    const scotusticianBucket = s3.Bucket.fromBucketName(
      this,
      'ScotusticianBucket',
      'scotustician'
    );

    // const scotusticianBucket = new s3.Bucket(this, 'ScotusticianBucket', {
    //   bucketName: 'scotustician',
    //   removalPolicy: cdk.RemovalPolicy.RETAIN,
    //   encryption: s3.BucketEncryption.S3_MANAGED,
    //   blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    // });

    const vpc = new ec2.Vpc(this, 'ScotusticianVpc', {
      maxAzs: 2,
      natGateways: 0, // Cost optimization: no NAT gateways
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: 'isolated-subnet',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
        },
      ],
    });

    const dbSecurityGroup = new ec2.SecurityGroup(this, 'ScotusticianDbSecurityGroup', {
      vpc,
      description: 'Security group for Scotustician RDS instance - restricted access',
      allowAllOutbound: false,
    });

    // Only allow access from within VPC CIDR range
    dbSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(5432),
      'Allow PostgreSQL access from VPC only'
    );

    const subnetGroup = new rds.SubnetGroup(this, 'ScotusticianDbSubnetGroup', {
      vpc,
      description: 'Subnet group for Scotustician RDS instance',
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
      },
    });

    const postgresInstance = new rds.DatabaseInstance(this, 'ScotusticianPostgresInstance', {
      engine: rds.DatabaseInstanceEngine.postgres({
  version: rds.PostgresEngineVersion.VER_16,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO), // Cost-effective
      vpc,
      subnetGroup,
      securityGroups: [dbSecurityGroup],
      
      databaseName: 'scotustician',
      credentials: rds.Credentials.fromGeneratedSecret('dbuser', {
        secretName: 'scotustician-db-credentials',
      }),
      
      allocatedStorage: 20,
      storageType: rds.StorageType.GP2,
      
      backupRetention: cdk.Duration.days(7),
      deletionProtection: false,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      
      storageEncrypted: true,
      publiclyAccessible: false, // Security: no public access
      
      parameterGroup: new rds.ParameterGroup(this, 'ScotusticianDbParameterGroup', {
        engine: rds.DatabaseInstanceEngine.postgres({
          version: rds.PostgresEngineVersion.VER_16,
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
    const secretsManagerEndpoint = new ec2.InterfaceVpcEndpoint(this, 'SecretsManagerVpcEndpoint', {
      vpc,
      service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
      subnets: {
        subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
      },
    });

    const s3Endpoint = new ec2.GatewayVpcEndpoint(this, 'S3VpcEndpoint', {
      vpc,
      service: ec2.GatewayVpcEndpointAwsService.S3,
      subnets: [{
        subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
      }],
    });

    // Lambda function for database initialization
    const dbInitFunction = new lambda.Function(this, 'DbInitFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda'), {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output'
          ],
        },
      }),
      vpc,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
      },
      securityGroups: [dbSecurityGroup],
      timeout: cdk.Duration.minutes(5),
      environment: {
        AWS_NODEJS_CONNECTION_REUSE_ENABLED: '1',
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    // Grant permissions to Lambda function
    postgresInstance.secret!.grantRead(dbInitFunction);

    // Add resource policy to restrict secret access to specific IAM user only
    const secretResourcePolicy = new iam.PolicyDocument({
      statements: [
        new iam.PolicyStatement({
          sid: 'AllowScotusticianUserAccess',
          effect: iam.Effect.ALLOW,
          principals: [new iam.ArnPrincipal(scotusticianUserArn)],
          actions: [
            'secretsmanager:GetSecretValue',
            'secretsmanager:DescribeSecret'
          ],
          resources: ['*'],
        }),
        new iam.PolicyStatement({
          sid: 'AllowLambdaInitAccess',
          effect: iam.Effect.ALLOW,
          principals: [new iam.ArnPrincipal(dbInitFunction.role!.roleArn)],
          actions: [
            'secretsmanager:GetSecretValue',
            'secretsmanager:DescribeSecret'
          ],
          resources: ['*'],
        }),
      ],
    });

    // Create a separate resource policy for the database secret
    new secretsmanager.CfnResourcePolicy(this, 'DbSecretResourcePolicy', {
      secretId: postgresInstance.secret!.secretArn,
      resourcePolicy: secretResourcePolicy.toJSON(),
    });
    
    // Allow Lambda to connect to RDS
    dbSecurityGroup.addIngressRule(
      dbSecurityGroup,
      ec2.Port.tcp(5432),
      'Allow Lambda to connect to RDS'
    );

    // Allow Lambda to connect to RDS PostgreSQL
    dbSecurityGroup.addEgressRule(
      dbSecurityGroup,
      ec2.Port.tcp(5432),
      'Allow Lambda to connect to RDS'
    );

    // Allow Lambda to access VPC endpoints for AWS services
    dbSecurityGroup.addEgressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(443),
      'Allow HTTPS access to VPC endpoints'
    );

    // Custom resource to trigger database initialization
    const dbInitProvider = new cr.Provider(this, 'DbInitProvider', {
      onEventHandler: dbInitFunction,
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    const dbInitResource = new cdk.CustomResource(this, 'DbInitResource', {
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
    const ecsCluster = new ecs.Cluster(this, 'DbtEcsCluster', {
      vpc,
      clusterName: 'scotustician-dbt-cluster',
      containerInsights: true,
    });

    // Create CloudWatch Log Group for dbt
    const dbtLogGroup = new logs.LogGroup(this, 'DbtLogGroup', {
      logGroupName: '/ecs/scotustician-dbt',
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Create ECS Task Execution Role
    const dbtTaskExecutionRole = new iam.Role(this, 'DbtTaskExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    // Create ECS Task Role
    const dbtTaskRole = new iam.Role(this, 'DbtTaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    // Grant the task role access to the database secret
    postgresInstance.secret!.grantRead(dbtTaskRole);
    
    // Grant the task role access to S3 bucket for dbt artifacts
    scotusticianBucket.grantReadWrite(dbtTaskRole);

    // Create dbt Docker image asset
    const dbtImage = new ecr_assets.DockerImageAsset(this, 'DbtImage', {
      directory: path.join(__dirname, '../dbt'),
      platform: ecr_assets.Platform.LINUX_AMD64,
    });

    // Create Task Definition for dbt
    const dbtTaskDefinition = new ecs.FargateTaskDefinition(this, 'DbtTaskDefinition', {
      family: 'scotustician-dbt-task',
      memoryLimitMiB: 2048,
      cpu: 1024,
      executionRole: dbtTaskExecutionRole,
      taskRole: dbtTaskRole,
    });

    // Add container to task definition
    const dbtContainer = dbtTaskDefinition.addContainer('dbt-container', {
      image: ecs.ContainerImage.fromDockerImageAsset(dbtImage),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'dbt',
        logGroup: dbtLogGroup,
      }),
      environment: {
        DBT_TARGET: 'prod',
        AWS_DEFAULT_REGION: this.region,
        S3_BUCKET: scotusticianBucket.bucketName,
      },
      secrets: {
        DB_HOST: ecs.Secret.fromSecretsManager(postgresInstance.secret!, 'host'),
        DB_PORT: ecs.Secret.fromSecretsManager(postgresInstance.secret!, 'port'),
        DB_NAME: ecs.Secret.fromSecretsManager(postgresInstance.secret!, 'dbname'),
        DB_USER: ecs.Secret.fromSecretsManager(postgresInstance.secret!, 'username'),
        DB_PASSWORD: ecs.Secret.fromSecretsManager(postgresInstance.secret!, 'password'),
      },
    });

    // Create Security Group for ECS Tasks
    const dbtSecurityGroup = new ec2.SecurityGroup(this, 'DbtEcsSecurityGroup', {
      vpc,
      description: 'Security group for dbt ECS tasks',
      allowAllOutbound: false,
    });

    // Allow ECS tasks to connect to RDS
    dbtSecurityGroup.addEgressRule(
      dbSecurityGroup,
      ec2.Port.tcp(5432),
      'Allow dbt to connect to RDS'
    );

    // Allow RDS to accept connections from ECS tasks
    dbSecurityGroup.addIngressRule(
      dbtSecurityGroup,
      ec2.Port.tcp(5432),
      'Allow dbt ECS tasks to connect'
    );

    // Allow ECS tasks to access VPC endpoints
    dbtSecurityGroup.addEgressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(443),
      'Allow HTTPS access to VPC endpoints'
    );

    // Create EventBridge rule for scheduled dbt runs
    const dbtScheduleRule = new events.Rule(this, 'DbtScheduleRule', {
      ruleName: 'scotustician-dbt-schedule',
      description: 'Trigger dbt runs weekly on Sunday at 12 PM ET',
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '17',  // 12 PM ET = 5 PM UTC (4 PM during DST)
        weekDay: 'SUN',
      }),
    });

    // Add ECS task as target for the EventBridge rule
    dbtScheduleRule.addTarget(
      new targets.EcsTask({
        cluster: ecsCluster,
        taskDefinition: dbtTaskDefinition,
        taskCount: 1,
        subnetSelection: {
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
        },
        securityGroups: [dbtSecurityGroup],
        platformVersion: ecs.FargatePlatformVersion.LATEST,
      })
    );

    // Create a Lambda function to trigger dbt runs manually
    const dbtTriggerFunction = new lambda.Function(this, 'DbtTriggerFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      code: lambda.Code.fromInline(`
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
        SUBNET_IDS: JSON.stringify(vpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_ISOLATED }).subnetIds),
        SECURITY_GROUP_ID: dbtSecurityGroup.securityGroupId,
      },
      timeout: cdk.Duration.seconds(30),
    });

    // Grant Lambda permission to run ECS tasks
    dbtTriggerFunction.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ecs:RunTask',
      ],
      resources: [dbtTaskDefinition.taskDefinitionArn],
    }));

    dbtTriggerFunction.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'iam:PassRole',
      ],
      resources: [
        dbtTaskExecutionRole.roleArn,
        dbtTaskRole.roleArn,
      ],
    }));

    // Outputs
    new cdk.CfnOutput(this, 'DatabaseEndpoint', {
      value: postgresInstance.instanceEndpoint.hostname,
      description: 'RDS Postgres instance endpoint (VPC access only)',
    });

    new cdk.CfnOutput(this, 'DatabasePort', {
      value: postgresInstance.instanceEndpoint.port.toString(),
      description: 'RDS Postgres instance port',
    });

    new cdk.CfnOutput(this, 'VpcId', {
      value: vpc.vpcId,
      description: 'VPC ID for database access',
    });

    new cdk.CfnOutput(this, 'SecretArn', {
      value: postgresInstance.secret!.secretArn,
      description: 'ARN of the database credentials secret',
    });

    new cdk.CfnOutput(this, 'DbInitStatus', {
      value: 'Database initialization will run automatically after deployment',
      description: 'Database initialization status',
    });

    new cdk.CfnOutput(this, 'EcsClusterName', {
      value: ecsCluster.clusterName,
      description: 'ECS Cluster name for dbt',
    });

    new cdk.CfnOutput(this, 'DbtTaskDefinitionArn', {
      value: dbtTaskDefinition.taskDefinitionArn,
      description: 'dbt Task Definition ARN',
    });

    new cdk.CfnOutput(this, 'DbtTriggerFunctionName', {
      value: dbtTriggerFunction.functionName,
      description: 'Lambda function name to trigger dbt runs',
    });
  }
}
