import { Construct } from 'constructs';

import { Stack, StackProps, CfnOutput, Tags, DefaultStackSynthesizer } from 'aws-cdk-lib';
import { Vpc, SubnetType, GatewayVpcEndpointAwsService, InterfaceVpcEndpointAwsService } from 'aws-cdk-lib/aws-ec2';
import { Cluster } from 'aws-cdk-lib/aws-ecs';
import { Bucket, IBucket } from 'aws-cdk-lib/aws-s3';

export interface ScotusticianSharedStackProps extends StackProps {
  awsIamArn: string;
}

export class ScotusticianSharedStack extends Stack {
  public readonly awsIamArn: string;
  public readonly vpc: Vpc;
  public readonly ingestCluster: Cluster;
  public readonly cpuCluster: Cluster;
  public readonly transformersGpuCluster?: Cluster;
  public readonly scotusticianBucket: IBucket;

  constructor(scope: Construct, id: string, props: ScotusticianSharedStackProps) {
    const qualifier = scope.node.tryGetContext('@aws-cdk:bootstrap-qualifier') || 'sctstcn';
    
    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });
    this.awsIamArn = props.awsIamArn;

    // Apply resource tags to entire stack
    Tags.of(this).add('Stack', 'shared');

    // S3 bucket for all services (import existing bucket)
    this.scotusticianBucket = Bucket.fromBucketName(
      this,
      'ScotusticianBucket',
      'scotustician'
    );

    this.vpc = new Vpc(this, 'ScotusticianVpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'private',
          subnetType: SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    this.vpc.addGatewayEndpoint('S3Endpoint', {
      service: GatewayVpcEndpointAwsService.S3,
    });

    this.vpc.addInterfaceEndpoint('EcrEndpoint', {
      service: InterfaceVpcEndpointAwsService.ECR,
    });

    this.vpc.addInterfaceEndpoint('EcrDkrEndpoint', {
      service: InterfaceVpcEndpointAwsService.ECR_DOCKER,
    });

    this.vpc.addInterfaceEndpoint('LogsEndpoint', {
      service: InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
    });

    this.vpc.addInterfaceEndpoint('SecretsManagerEndpoint', {
      service: InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
    });

    // Create separate clusters for different workloads
    this.ingestCluster = new Cluster(this, 'IngestCluster', {
      vpc: this.vpc,
      clusterName: 'scotustician-ingest',
    });

    // Always create CPU cluster for shared workloads
    this.cpuCluster = new Cluster(this, 'CpuCluster', {
      vpc: this.vpc,
      clusterName: 'scotustician-cpu',
    });

    // Only create GPU cluster if GPU is available
    const useGpu = this.node.tryGetContext('useGpu') === 'true';
    if (useGpu) {
      this.transformersGpuCluster = new Cluster(this, 'GpuCluster', {
        vpc: this.vpc,
        clusterName: 'scotustician-gpu',
      });
    }

    new CfnOutput(this, 'IngestClusterName', {
      value: this.ingestCluster.clusterName,
    });

    new CfnOutput(this, 'CpuClusterName', {
      value: this.cpuCluster.clusterName,
    });

    if (useGpu) {
      new CfnOutput(this, 'GpuClusterName', {
        value: this.transformersGpuCluster!.clusterName,
      });
    }

    new CfnOutput(this, 'PublicSubnetId1', {
      value: this.vpc.publicSubnets[0].subnetId,
    });

    new CfnOutput(this, 'PublicSubnetId2', {
      value: this.vpc.publicSubnets[1].subnetId,
    });

    new CfnOutput(this, 'PrivateSubnetId1', {
      value: this.vpc.isolatedSubnets[0].subnetId,
    });

    new CfnOutput(this, 'PrivateSubnetId2', {
      value: this.vpc.isolatedSubnets[1].subnetId,
    });
  }
}