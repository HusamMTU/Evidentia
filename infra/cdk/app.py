#!/usr/bin/env python3
from __future__ import annotations

import os

import aws_cdk as cdk

from evidentia_cdk.foundation_stack import EvidentiaFoundationStack


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _context_or_env(app: cdk.App, key: str, env_key: str, default: str | None = None) -> str | None:
    value = app.node.try_get_context(key)
    if value is not None:
        return str(value)
    return os.getenv(env_key, default)


app = cdk.App()

stage = _context_or_env(app, "stage", "CDK_STAGE", "dev") or "dev"
account = _context_or_env(app, "account", "CDK_DEFAULT_ACCOUNT")
region = _context_or_env(app, "region", "CDK_DEFAULT_REGION")

raw_bucket_name = _context_or_env(app, "rawBucketName", "EVIDENTIA_RAW_BUCKET")
assets_bucket_name = _context_or_env(app, "assetsBucketName", "EVIDENTIA_ASSETS_BUCKET")
vectors_bucket_name = _context_or_env(app, "vectorsBucketName", "EVIDENTIA_VECTORS_BUCKET")
api_runtime_principal = _context_or_env(
    app,
    "apiRuntimePrincipal",
    "EVIDENTIA_API_RUNTIME_PRINCIPAL",
    "lambda.amazonaws.com",
) or "lambda.amazonaws.com"
enable_bedrock_kb = _as_bool(
    _context_or_env(app, "enableBedrockKb", "EVIDENTIA_ENABLE_BEDROCK_KB"),
    default=False,
)
knowledge_base_name = _context_or_env(app, "knowledgeBaseName", "BEDROCK_KNOWLEDGE_BASE_NAME")
knowledge_base_data_source_name = _context_or_env(
    app, "knowledgeBaseDataSourceName", "BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_NAME"
)
embedding_model_arn = _context_or_env(app, "embeddingModelArn", "BEDROCK_EMBEDDING_MODEL_ARN")
s3_vectors_index_name = _context_or_env(app, "s3VectorsIndexName", "BEDROCK_S3_VECTORS_INDEX_NAME")
advanced_parsing_strategy = _context_or_env(
    app, "advancedParsingStrategy", "BEDROCK_ADVANCED_PARSING_STRATEGY"
)
advanced_parsing_model_arn = _context_or_env(
    app, "advancedParsingModelArn", "BEDROCK_ADVANCED_PARSING_MODEL_ARN"
)
advanced_parsing_modality = _context_or_env(
    app, "advancedParsingModality", "BEDROCK_ADVANCED_PARSING_MODALITY"
)

stack_env = cdk.Environment(account=account, region=region)

EvidentiaFoundationStack(
    app,
    f"EvidentiaFoundation-{stage}",
    stage_name=stage,
    raw_bucket_name=raw_bucket_name,
    assets_bucket_name=assets_bucket_name,
    vectors_bucket_name=vectors_bucket_name,
    api_runtime_principal=api_runtime_principal,
    enable_bedrock_kb=enable_bedrock_kb,
    knowledge_base_name=knowledge_base_name,
    knowledge_base_data_source_name=knowledge_base_data_source_name,
    embedding_model_arn=embedding_model_arn,
    s3_vectors_index_name=s3_vectors_index_name,
    advanced_parsing_strategy=advanced_parsing_strategy,
    advanced_parsing_model_arn=advanced_parsing_model_arn,
    advanced_parsing_modality=advanced_parsing_modality,
    env=stack_env,
)

app.synth()
