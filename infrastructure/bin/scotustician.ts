import * as cdk from 'aws-cdk-lib';
import { ScotusticianSharedStack } from '../lib/scotustician-shared-stack';
import { ScotusticianIngestStack } from '../lib/scotustician-ingest-stack';
import { ScotusticianTransformersStack } from '../lib/scotustician-transformers-stack';
import { ScotusticianClusteringStack } from '../lib/scotustician-clustering-stack';
import { ScotusticianVisualizationStack } from '../lib/scotustician-visualization-stack';

process.env.CDK_BOOTSTRAP_QUALIFIER = process.env.CDK_BOOTSTRAP_QUALIFIER || 'sctstcn';

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION,
};

const app = new cdk.App();

const shared = new ScotusticianSharedStack(app, 'ScotusticianSharedStack', { env });

const ingest = new ScotusticianIngestStack(app, 'ScotusticianIngestStack', {
  cluster: shared.ingestCluster,
  vpc: shared.vpc,
  env,
});

const useGpu = app.node.tryGetContext('useGpu') === 'true';

new ScotusticianTransformersStack(app, 'ScotusticianTransformersStack', {
  cluster: useGpu && shared.transformersGpuCluster ? shared.transformersGpuCluster : shared.transformersCpuCluster,
  vpc: shared.vpc,
  ingestTaskDefinitionArn: ingest.taskDefinitionArn,
  env,
});

new ScotusticianClusteringStack(app, 'ScotusticianClusteringStack', {
  cluster: shared.transformersCpuCluster, // Always use CPU cluster for clustering
  vpc: shared.vpc,
  env,
});

new ScotusticianVisualizationStack(app, 'ScotusticianVisualizationStack', {
  vpc: shared.vpc,
  env,
});
