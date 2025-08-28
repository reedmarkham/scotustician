import * as cdk from 'aws-cdk-lib';
import { ScotusticianSharedStack } from '../lib/scotustician-shared-stack';
import { ScotusticianDbStack } from '../lib/scotustician-db-stack';
import { ScotusticianIngestStack } from '../lib/scotustician-ingest-stack';
import { ScotusticianTransformersStack } from '../lib/scotustician-transformers-stack';
import { ScotusticianClusteringStack } from '../lib/scotustician-clustering-stack';
import { ScotusticianVisualizationStack } from '../lib/scotustician-visualization-stack';
import { ScotusticianOrchestrationStack } from '../lib/scotustician-orchestration-stack';

process.env.CDK_BOOTSTRAP_QUALIFIER = process.env.CDK_BOOTSTRAP_QUALIFIER || 'sctstcn';

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION,
};

const app = new cdk.App();


const shared = new ScotusticianSharedStack(app, 'ScotusticianSharedStack', { env });

// Deploy DB stack after shared, using the same VPC
const db = new ScotusticianDbStack(app, 'ScotusticianDbStack', {
  env,
  // vpc: shared.vpc, // Uncomment if your constructor supports passing VPC
});

const ingest = new ScotusticianIngestStack(app, 'ScotusticianIngestStack', {
  cluster: shared.ingestCluster,
  vpc: shared.vpc,
  env,
});

const useGpu = app.node.tryGetContext('useGpu') === 'true';

const transformers = new ScotusticianTransformersStack(app, 'ScotusticianTransformersStack', {
  cluster: useGpu && shared.transformersGpuCluster ? shared.transformersGpuCluster : shared.cpuCluster,
  vpc: shared.vpc,
  ingestTaskDefinitionArn: ingest.taskDefinitionArn,
  env,
});

const clustering = new ScotusticianClusteringStack(app, 'ScotusticianClusteringStack', {
  cluster: shared.cpuCluster,
  vpc: shared.vpc,
  env,
});

new ScotusticianVisualizationStack(app, 'ScotusticianVisualizationStack', {
  vpc: shared.vpc,
  env,
});

new ScotusticianOrchestrationStack(app, 'ScotusticianOrchestrationStack', {
  ingestClusterArn: shared.ingestCluster.clusterArn,
  ingestTaskDefinitionArn: ingest.taskDefinitionArn,
  transformersJobQueueArn: transformers.jobQueueArn,
  transformersJobDefinitionArn: transformers.jobDefinitionArn,
  clusteringJobQueueArn: clustering.jobQueueArn,
  clusteringJobDefinitionArn: clustering.jobDefinitionArn,
  vpcId: shared.vpc.vpcId,
  publicSubnetIds: shared.vpc.publicSubnets.map(sn => sn.subnetId),
  privateSubnetIds: shared.vpc.privateSubnets.map(sn => sn.subnetId),
  env,
});
