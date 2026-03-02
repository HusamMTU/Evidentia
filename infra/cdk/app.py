#!/usr/bin/env python3
from __future__ import annotations

import os

import aws_cdk as cdk

from evidentia_cdk.foundation_stack import EvidentiaFoundationStack


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _context_or_env(app: cdk.App, key: str, env_key: str, default: str | None = None) -> str | None:
    value = app.node.try_get_context(key)
    if value is not None:
        normalized = _normalize_optional(str(value))
        if normalized is not None:
            return normalized

    env_value = _normalize_optional(os.getenv(env_key))
    if env_value is not None:
        return env_value

    return default


app = cdk.App()

stage = _context_or_env(app, "stage", "CDK_STAGE", "dev") or "dev"
account = _context_or_env(app, "account", "CDK_DEFAULT_ACCOUNT")
region = _context_or_env(app, "region", "CDK_DEFAULT_REGION")

# NOTE: deploy-time explicit names use INFRA_* keys to avoid collisions with runtime
# values written from stack outputs (EVIDENTIA_*).
raw_bucket_name = _context_or_env(app, "rawBucketName", "INFRA_RAW_BUCKET_NAME")
assets_bucket_name = _context_or_env(app, "assetsBucketName", "INFRA_ASSETS_BUCKET_NAME")
vectors_bucket_name = _context_or_env(app, "vectorsBucketName", "INFRA_VECTORS_BUCKET_NAME")
ingestion_manifest_table_name = _context_or_env(
    app,
    "ingestionManifestTableName",
    "INFRA_INGESTION_MANIFEST_TABLE_NAME",
)
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
s3_vectors_index_name = _context_or_env(app, "s3VectorsIndexName", "INFRA_S3_VECTORS_INDEX_NAME")
s3_vectors_non_filterable_metadata_keys_raw = _context_or_env(
    app,
    "s3VectorsNonFilterableMetadataKeys",
    "INFRA_S3_VECTORS_NON_FILTERABLE_METADATA_KEYS",
)
s3_vectors_non_filterable_metadata_keys = (
    tuple(
        key.strip()
        for key in (s3_vectors_non_filterable_metadata_keys_raw or "").split(",")
        if key.strip()
    )
    or None
)
s3_vectors_data_type = (
    _context_or_env(app, "s3VectorsDataType", "BEDROCK_S3_VECTORS_DATA_TYPE", "float32")
    or "float32"
)
s3_vectors_distance_metric = (
    _context_or_env(app, "s3VectorsDistanceMetric", "BEDROCK_S3_VECTORS_DISTANCE_METRIC", "cosine")
    or "cosine"
)
s3_vectors_dimension_raw = _context_or_env(
    app, "s3VectorsDimension", "BEDROCK_S3_VECTORS_DIMENSION", "1024"
)
try:
    s3_vectors_dimension = int(s3_vectors_dimension_raw or "1024")
except ValueError as exc:
    raise ValueError(
        f"Invalid s3VectorsDimension/BEDROCK_S3_VECTORS_DIMENSION: {s3_vectors_dimension_raw!r}"
    ) from exc
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
    ingestion_manifest_table_name=ingestion_manifest_table_name,
    api_runtime_principal=api_runtime_principal,
    enable_bedrock_kb=enable_bedrock_kb,
    knowledge_base_name=knowledge_base_name,
    knowledge_base_data_source_name=knowledge_base_data_source_name,
    embedding_model_arn=embedding_model_arn,
    s3_vectors_index_name=s3_vectors_index_name,
    s3_vectors_non_filterable_metadata_keys=s3_vectors_non_filterable_metadata_keys,
    s3_vectors_data_type=s3_vectors_data_type,
    s3_vectors_dimension=s3_vectors_dimension,
    s3_vectors_distance_metric=s3_vectors_distance_metric,
    advanced_parsing_strategy=advanced_parsing_strategy,
    advanced_parsing_model_arn=advanced_parsing_model_arn,
    advanced_parsing_modality=advanced_parsing_modality,
    env=stack_env,
)

app.synth()
