import { Stack, StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface ScotusticianTransformersStackProps extends StackProps {
  vpc: ec2.IVpc;
  cluster: ecs.Cluster;
}

export class ScotusticianTransformersStack extends Stack {
  constructor(scope: Construct, id: string, props: ScotusticianTransformersStackProps) {
    super(scope, id, props);

    const { vpc, cluster } = props;

    const cudaAmiId = 'ami-0a5c3f3f0d46b69db'; // ECS-optimized GPU AMI (us-east-1)

    // --- EC2 ASG with GPU Instances ---
    const autoScalingGroup = new autoscaling.AutoScalingGroup(this, 'GPUFleet', {
      vpc,
      instanceType: new ec2.InstanceType('g4dn.xlarge'),
      machineImage: ec2.MachineImage.genericLinux({ 'us-east-1': cudaAmiId }),
      minCapacity: 1,
    });

    const capacityProvider = new ecs.AsgCapacityProvider(this, 'AsgCapacityProvider', {
      autoScalingGroup,
    });

    cluster.addAsgCapacityProvider(capacityProvider);

    // --- Docker Image Asset (builds ../transformers) ---
    const image = new ecr_assets.DockerImageAsset(this, 'TransformersImage', {
      directory: '../transformers',
    });

    // --- ECS Task Definition (EC2 + GPU) ---
    const taskDefinition = new ecs.Ec2TaskDefinition(this, 'TransformersTaskDef', {
      networkMode: ecs.NetworkMode.AWS_VPC,
    });

    const container = taskDefinition.addContainer('TransformersContainer', {
      image: ecs.ContainerImage.fromDockerImageAsset(image),
      memoryLimitMiB: 8192,
      cpu: 1024,
      gpuCount: 1,
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'transformers' }),
      environment: {
        OPENSEARCH_HOST: process.env.OPENSEARCH_HOST || 'https://your-domain.region.es.amazonaws.com',
        S3_BUCKET: 'scotustician',
        MAX_WORKERS: '4',
      },
      command: ['python', 'batch_embed.py'], // Entry point
    });

    container.addUlimits({
      name: ecs.UlimitName.NOFILE,
      softLimit: 65536,
      hardLimit: 65536,
    });

    // --- IAM Permissions for S3 + OpenSearch ---
    taskDefinition.taskRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonS3FullAccess')
    );

    taskDefinition.taskRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonOpenSearchServiceFullAccess')
    );
  }
}
