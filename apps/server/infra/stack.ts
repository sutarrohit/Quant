import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { NodejsFunction } from "aws-cdk-lib/aws-lambda-nodejs";
import * as path from "path";
import { fileURLToPath } from "url";
import * as dotenv from "dotenv";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load environment variables from .env.production if it exists
dotenv.config({ path: path.resolve(__dirname, "../.env.production") });

export class repoServerStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const serverRoot = path.resolve(__dirname, "..");

    const fn = new NodejsFunction(this, "repoServerFunction", {
      entry: path.join(__dirname, "../lambda/index.ts"),
      handler: "handler",
      runtime: lambda.Runtime.NODEJS_22_X,
      memorySize: 256,
      timeout: cdk.Duration.seconds(30),
      environment: {
        NODE_ENV: "production",
        PORT: process.env.PORT || "",
        FRONTEND_URL: process.env.FRONTEND_URL || "",
        LOG_LEVEL: process.env.LOG_LEVEL || "info",
        DATABASE_URL: process.env.DATABASE_URL || "",
        DIRECT_URL: process.env.DIRECT_URL || ""
      },
      bundling: {
        minify: true,
        sourceMap: true,
        target: "node22",
        format: cdk.aws_lambda_nodejs.OutputFormat.ESM,
        mainFields: ["module", "main"],
        // Let esbuild resolve @/* path aliases from tsconfig
        tsconfig: path.join(__dirname, "../tsconfig.json"),
        // ESM banner: needed for packages that use require()
        banner: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);"
      }
    });

    // Add a Function URL (no API Gateway needed)
    const fnUrl = fn.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE
    });

    new cdk.CfnOutput(this, "FunctionUrl", {
      value: fnUrl.url,
      description: "repo Server Lambda Function URL"
    });

    new cdk.CfnOutput(this, "FunctionName", {
      value: fn.functionName,
      description: "Lambda Function Name"
    });
  }
}

const app = new cdk.App();
new repoServerStack(app, "repoServerStack", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || "us-east-1"
  }
});
