import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import { Construct } from 'constructs';

export interface ScotusticianSharedStackProps extends cdk.StackProps {
  awsIamArn: string;
}

export class ScotusticianSharedStack extends cdk.Stack {
  public readonly awsIamArn: string;
  public readonly vpc: ec2.Vpc;
  public readonly ingestCluster: ecs.Cluster;
  public readonly cpuCluster: ecs.Cluster;
  public readonly transformersGpuCluster?: ecs.Cluster;

  constructor(scope: Construct, id: string, props: ScotusticianSharedStackProps) {
    super(scope, id, props);
    this.awsIamArn = props.awsIamArn;

  const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';
  const useGpu = scope.node.tryGetContext('useGpu') === 'true';
  // ...existing code...

    // Apply resource tags to entire stack
    cdk.Tags.of(this).add('Project', 'scotustician');
    cdk.Tags.of(this).add('Stack', 'shared');

    this.vpc = new ec2.Vpc(this, 'ScotusticianVpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'private',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    this.vpc.addGatewayEndpoint('S3Endpoint', {
      service: ec2.GatewayVpcEndpointAwsService.S3,
    });

    this.vpc.addInterfaceEndpoint('EcrEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.ECR,
    });

    this.vpc.addInterfaceEndpoint('EcrDkrEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
    });

    this.vpc.addInterfaceEndpoint('LogsEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
    });

    this.vpc.addInterfaceEndpoint('SecretsManagerEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
    });

    // Create separate clusters for different workloads
    this.ingestCluster = new ecs.Cluster(this, 'IngestCluster', {
      vpc: this.vpc,
      clusterName: 'scotustician-ingest',
    });

    // Always create CPU cluster for shared workloads
    this.cpuCluster = new ecs.Cluster(this, 'CpuCluster', {
      vpc: this.vpc,
      clusterName: 'scotustician-cpu',
    });

    // Only create GPU cluster if GPU is available
    if (useGpu) {
      this.transformersGpuCluster = new ecs.Cluster(this, 'GpuCluster', {
        vpc: this.vpc,
        clusterName: 'scotustician-gpu',
      });
    }


    new cdk.CfnOutput(this, 'IngestClusterName', {
      value: this.ingestCluster.clusterName,
    });

    new cdk.CfnOutput(this, 'CpuClusterName', {
      value: this.cpuCluster.clusterName,
    });

    if (useGpu) {
      new cdk.CfnOutput(this, 'GpuClusterName', {
        value: this.transformersGpuCluster!.clusterName,
      });
    }

    new cdk.CfnOutput(this, 'PublicSubnetId1', {
      value: this.vpc.publicSubnets[0].subnetId,
    });

    new cdk.CfnOutput(this, 'PublicSubnetId2', {
      value: this.vpc.publicSubnets[1].subnetId,
    });

    new cdk.CfnOutput(this, 'PrivateSubnetId1', {
      value: this.vpc.isolatedSubnets[0].subnetId,
    });

    new cdk.CfnOutput(this, 'PrivateSubnetId2', {
      value: this.vpc.isolatedSubnets[1].subnetId,
    });
  }
}