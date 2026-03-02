from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from aws_cdk import (
    CfnOutput,
    CfnDeletionPolicy,
    Duration,
    RemovalPolicy,
    Stack,
    aws_bedrock as bedrock,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3vectors as s3vectors,
)
from constructs import Construct


RAW_PREFIX = "documents-raw"
BEDROCK_ASSETS_PREFIX_TEMPLATE = (
    "aws/bedrock/knowledge_bases/{knowledge_base_id}/{data_source_id}/{asset_uuid}.png"
)
INGESTION_MANIFEST_SOURCE_URI_INDEX_NAME = "source_uri-index"


@dataclass(frozen=True)
class FoundationStackProps:
    stage_name: str
    raw_bucket_name: str | None = None
    assets_bucket_name: str | None = None
    vectors_bucket_name: str | None = None
    ingestion_manifest_table_name: str | None = None
    api_runtime_principal: str = "lambda.amazonaws.com"
    enable_bedrock_kb: bool = False
    knowledge_base_name: str | None = None
    knowledge_base_data_source_name: str | None = None
    embedding_model_arn: str | None = None
    s3_vectors_index_name: str | None = None
    s3_vectors_non_filterable_metadata_keys: tuple[str, ...] | None = None
    s3_vectors_data_type: str = "float32"
    s3_vectors_dimension: int = 1024
    s3_vectors_distance_metric: str = "cosine"
    advanced_parsing_strategy: str | None = None
    advanced_parsing_model_arn: str | None = None
    advanced_parsing_modality: str | None = None


class EvidentiaFoundationStack(Stack):
    """Phase 1 foundation resources for Evidentia.

    This stack provisions storage, IAM, and (optionally) Bedrock KB resources for
    phased rollouts and troubleshooting.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_name: str,
        raw_bucket_name: str | None = None,
        assets_bucket_name: str | None = None,
        vectors_bucket_name: str | None = None,
        ingestion_manifest_table_name: str | None = None,
        api_runtime_principal: str = "lambda.amazonaws.com",
        enable_bedrock_kb: bool = False,
        knowledge_base_name: str | None = None,
        knowledge_base_data_source_name: str | None = None,
        embedding_model_arn: str | None = None,
        s3_vectors_index_name: str | None = None,
        s3_vectors_non_filterable_metadata_keys: tuple[str, ...] | None = None,
        s3_vectors_data_type: str = "float32",
        s3_vectors_dimension: int = 1024,
        s3_vectors_distance_metric: str = "cosine",
        advanced_parsing_strategy: str | None = None,
        advanced_parsing_model_arn: str | None = None,
        advanced_parsing_modality: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        props = FoundationStackProps(
            stage_name=stage_name,
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
        )

        raw_bucket = self._create_bucket(
            "RawDocumentsBucket",
            explicit_name=props.raw_bucket_name,
            auto_delete_objects=False,
        )
        assets_bucket = self._create_bucket(
            "ExtractedAssetsBucket",
            explicit_name=props.assets_bucket_name,
            auto_delete_objects=False,
        )
        vectors_bucket, vectors_index = self._create_s3_vectors_resources(
            stage_name=props.stage_name,
            vector_bucket_name=props.vectors_bucket_name,
            index_name=props.s3_vectors_index_name,
            non_filterable_metadata_keys=props.s3_vectors_non_filterable_metadata_keys,
            data_type=props.s3_vectors_data_type,
            dimension=props.s3_vectors_dimension,
            distance_metric=props.s3_vectors_distance_metric,
        )
        ingestion_manifest_table = self._create_ingestion_manifest_table(
            explicit_name=props.ingestion_manifest_table_name
        )

        kb_role = self._create_kb_role(
            raw_bucket=raw_bucket,
            assets_bucket=assets_bucket,
            vectors_bucket=vectors_bucket,
            vectors_index=vectors_index,
            embedding_model_arn=props.embedding_model_arn,
        )
        api_role = self._create_api_role(
            assets_bucket=assets_bucket,
            ingestion_manifest_table=ingestion_manifest_table,
            api_runtime_principal=props.api_runtime_principal,
        )

        kb_resource = None
        data_source_resource = None
        if props.enable_bedrock_kb:
            kb_resource, data_source_resource = self._create_bedrock_knowledge_base_resources(
                stage_name=props.stage_name,
                raw_bucket=raw_bucket,
                assets_bucket=assets_bucket,
                vectors_bucket=vectors_bucket,
                vectors_index=vectors_index,
                kb_role=kb_role,
                knowledge_base_name=props.knowledge_base_name,
                knowledge_base_data_source_name=props.knowledge_base_data_source_name,
                embedding_model_arn=props.embedding_model_arn,
                advanced_parsing_strategy=props.advanced_parsing_strategy,
                advanced_parsing_model_arn=props.advanced_parsing_model_arn,
                advanced_parsing_modality=props.advanced_parsing_modality,
            )

        self._emit_outputs(
            raw_bucket=raw_bucket,
            assets_bucket=assets_bucket,
            vectors_bucket=vectors_bucket,
            vectors_index=vectors_index,
            ingestion_manifest_table=ingestion_manifest_table,
            kb_role=kb_role,
            api_role=api_role,
            stage_name=props.stage_name,
            kb_resource=kb_resource,
            data_source_resource=data_source_resource,
        )

    def _create_s3_vectors_resources(
        self,
        *,
        stage_name: str,
        vector_bucket_name: str | None,
        index_name: str | None,
        non_filterable_metadata_keys: tuple[str, ...] | None,
        data_type: str,
        dimension: int,
        distance_metric: str,
    ) -> tuple[s3vectors.CfnVectorBucket, s3vectors.CfnIndex]:
        vector_bucket = s3vectors.CfnVectorBucket(
            self,
            "S3VectorsBucket",
            vector_bucket_name=vector_bucket_name,
        )
        vector_bucket.cfn_options.deletion_policy = CfnDeletionPolicy.RETAIN
        vector_bucket.cfn_options.update_replace_policy = CfnDeletionPolicy.RETAIN

        # Bedrock KB ingestion often writes large chunk/context metadata; without
        # these keys marked non-filterable, S3 Vectors can fail at 2KB filterable
        # metadata limits.
        effective_non_filterable_keys = tuple(
            key for key in (non_filterable_metadata_keys or ()) if key.strip()
        ) or (
            "AMAZON_BEDROCK_TEXT",
            "AMAZON_BEDROCK_METADATA",
        )
        if index_name:
            effective_index_name = self._normalize_s3vectors_index_name(index_name)
        else:
            effective_index_name = self._default_s3vectors_index_name(
                stage_name=stage_name,
                data_type=data_type,
                dimension=dimension,
                distance_metric=distance_metric,
                non_filterable_metadata_keys=effective_non_filterable_keys,
            )
        vector_index = s3vectors.CfnIndex(
            self,
            "S3VectorsIndex",
            data_type=data_type.lower(),
            dimension=dimension,
            distance_metric=distance_metric.lower(),
            index_name=effective_index_name,
            vector_bucket_arn=vector_bucket.attr_vector_bucket_arn,
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=list(effective_non_filterable_keys)
            ),
        )
        vector_index.cfn_options.deletion_policy = CfnDeletionPolicy.RETAIN
        vector_index.cfn_options.update_replace_policy = CfnDeletionPolicy.RETAIN
        vector_index.add_dependency(vector_bucket)

        return vector_bucket, vector_index

    def _create_bucket(
        self,
        logical_id: str,
        *,
        explicit_name: str | None,
        auto_delete_objects: bool,
    ) -> s3.Bucket:
        bucket = s3.Bucket(
            self,
            logical_id,
            bucket_name=explicit_name,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=auto_delete_objects,
        )

        # Keep incomplete multipart uploads from accumulating in long-running environments.
        bucket.add_lifecycle_rule(
            abort_incomplete_multipart_upload_after=Duration.days(7)
        )
        return bucket

    def _create_ingestion_manifest_table(
        self,
        *,
        explicit_name: str | None,
    ) -> dynamodb.Table:
        table = dynamodb.Table(
            self,
            "IngestionManifestTable",
            table_name=explicit_name,
            partition_key=dynamodb.Attribute(
                name="doc_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )
        table.add_global_secondary_index(
            index_name=INGESTION_MANIFEST_SOURCE_URI_INDEX_NAME,
            partition_key=dynamodb.Attribute(
                name="source_uri",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        return table

    def _create_kb_role(
        self,
        *,
        raw_bucket: s3.Bucket,
        assets_bucket: s3.Bucket,
        vectors_bucket: s3vectors.CfnVectorBucket,
        vectors_index: s3vectors.CfnIndex,
        embedding_model_arn: str | None,
    ) -> iam.Role:
        role = iam.Role(
            self,
            "KnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Bedrock Knowledge Base role for Evidentia raw document ingestion and asset extraction.",
        )

        raw_bucket.grant_read(role)
        assets_bucket.grant_read_write(role)

        role.add_to_policy(
            iam.PolicyStatement(
                sid="ListRawAndAssetPrefixes",
                actions=["s3:ListBucket"],
                resources=[raw_bucket.bucket_arn, assets_bucket.bucket_arn],
            )
        )
        invoke_resources = [embedding_model_arn] if embedding_model_arn else ["*"]
        role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeEmbeddingModel",
                actions=["bedrock:InvokeModel"],
                resources=invoke_resources,
            )
        )

        # Placeholder for S3 Vectors / KB-specific permissions to be tightened once the
        # exact service-level permissions are confirmed in the target environment.
        role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockKnowledgeBaseControlPlanePlaceholder",
                actions=[
                    "bedrock:CreateKnowledgeBase",
                    "bedrock:UpdateKnowledgeBase",
                    "bedrock:DeleteKnowledgeBase",
                    "bedrock:CreateDataSource",
                    "bedrock:UpdateDataSource",
                    "bedrock:DeleteDataSource",
                    "bedrock:StartIngestionJob",
                    "bedrock:GetKnowledgeBase",
                    "bedrock:GetDataSource",
                    "bedrock:GetIngestionJob",
                ],
                resources=["*"],
            )
        )
        # Required when advanced parsing uses BEDROCK_DATA_AUTOMATION.
        role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockDataAutomationRuntime",
                actions=[
                    "bedrock:InvokeDataAutomationAsync",
                    "bedrock:GetDataAutomationStatus",
                ],
                resources=["*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="S3VectorsPermissions",
                actions=["s3vectors:*"],
                resources=[vectors_bucket.attr_vector_bucket_arn, vectors_index.attr_index_arn],
            )
        )

        return role

    def _create_api_role(
        self,
        *,
        assets_bucket: s3.Bucket,
        ingestion_manifest_table: dynamodb.Table,
        api_runtime_principal: str,
    ) -> iam.Role:
        role = iam.Role(
            self,
            "ApiRuntimeRole",
            assumed_by=iam.ServicePrincipal(api_runtime_principal),
            description="API runtime role for Evidentia query retrieval, asset presigning, and Claude invocation.",
        )

        assets_bucket.grant_read(role)
        ingestion_manifest_table.grant_read_write_data(role)

        role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockRetrieveAndInvoke",
                actions=[
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:GetKnowledgeBase",
                ],
                resources=["*"],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                sid="AllowListAssetsBucketForPresignWorkflows",
                actions=["s3:ListBucket"],
                resources=[assets_bucket.bucket_arn],
            )
        )

        if api_runtime_principal == "lambda.amazonaws.com":
            role.add_managed_policy(
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            )

        return role

    def _create_bedrock_knowledge_base_resources(
        self,
        *,
        stage_name: str,
        raw_bucket: s3.Bucket,
        assets_bucket: s3.Bucket,
        vectors_bucket: s3vectors.CfnVectorBucket,
        vectors_index: s3vectors.CfnIndex,
        kb_role: iam.Role,
        knowledge_base_name: str | None,
        knowledge_base_data_source_name: str | None,
        embedding_model_arn: str | None,
        advanced_parsing_strategy: str | None,
        advanced_parsing_model_arn: str | None,
        advanced_parsing_modality: str | None,
    ) -> tuple[bedrock.CfnKnowledgeBase, bedrock.CfnDataSource]:
        if not embedding_model_arn:
            raise ValueError(
                "enable_bedrock_kb=True requires embedding_model_arn "
                "(context: embeddingModelArn or env: BEDROCK_EMBEDDING_MODEL_ARN)"
            )
        kb_name = knowledge_base_name or self._default_bedrock_resource_name(
            suffix="kb",
            stage_name=stage_name,
            fingerprint_seed="|".join(
                [
                    "kb-v2",
                    stage_name,
                    embedding_model_arn,
                    advanced_parsing_strategy or "",
                    advanced_parsing_model_arn or "",
                    advanced_parsing_modality or "",
                ]
            ),
        )
        ds_name = knowledge_base_data_source_name or self._default_bedrock_resource_name(
            suffix="raw-s3",
            stage_name=stage_name,
            fingerprint_seed=f"ds-v2|{stage_name}|{RAW_PREFIX}",
        )
        parsing_strategy = (advanced_parsing_strategy or "").strip().upper()

        vector_kb_config_kwargs: dict[str, object] = {"embedding_model_arn": embedding_model_arn}
        if parsing_strategy:
            vector_kb_config_kwargs["supplemental_data_storage_configuration"] = (
                bedrock.CfnKnowledgeBase.SupplementalDataStorageConfigurationProperty(
                    supplemental_data_storage_locations=[
                        bedrock.CfnKnowledgeBase.SupplementalDataStorageLocationProperty(
                            supplemental_data_storage_location_type="S3",
                            s3_location=bedrock.CfnKnowledgeBase.S3LocationProperty(
                                uri=f"s3://{assets_bucket.bucket_name}"
                            ),
                        )
                    ]
                )
            )

        kb_props: dict[str, object] = {
            "name": kb_name,
            "role_arn": kb_role.role_arn,
            "description": "Evidentia multimodal grounded document intelligence knowledge base.",
            "knowledge_base_configuration": bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    **vector_kb_config_kwargs
                ),
            ),
            "storage_configuration": bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    vector_bucket_arn=vectors_bucket.attr_vector_bucket_arn,
                    index_arn=vectors_index.attr_index_arn,
                ),
            ),
        }
        knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "BedrockKnowledgeBase",
            **kb_props,
        )
        kb_default_policy = kb_role.node.try_find_child("DefaultPolicy")
        if kb_default_policy is not None:
            knowledge_base.node.add_dependency(kb_default_policy)

        vector_ingestion_configuration = self._build_vector_ingestion_configuration(
            advanced_parsing_strategy=advanced_parsing_strategy,
            advanced_parsing_model_arn=advanced_parsing_model_arn,
            advanced_parsing_modality=advanced_parsing_modality,
        )

        data_source_props: dict[str, object] = {
            "name": ds_name,
            "knowledge_base_id": knowledge_base.attr_knowledge_base_id,
            "description": "Raw PDF source for Evidentia documents",
            "data_source_configuration": bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=raw_bucket.bucket_arn,
                    inclusion_prefixes=[f"{RAW_PREFIX}/"],
                ),
            ),
            "data_deletion_policy": "RETAIN",
        }
        if vector_ingestion_configuration is not None:
            data_source_props["vector_ingestion_configuration"] = vector_ingestion_configuration

        data_source = bedrock.CfnDataSource(self, "BedrockKnowledgeBaseDataSource", **data_source_props)
        data_source.add_dependency(knowledge_base)
        if kb_default_policy is not None:
            data_source.node.add_dependency(kb_default_policy)

        return knowledge_base, data_source

    def _build_vector_ingestion_configuration(
        self,
        *,
        advanced_parsing_strategy: str | None,
        advanced_parsing_model_arn: str | None,
        advanced_parsing_modality: str | None,
    ) -> bedrock.CfnDataSource.VectorIngestionConfigurationProperty | None:
        parsing_strategy = (advanced_parsing_strategy or "").strip().upper()
        if not parsing_strategy:
            return None

        parsing_configuration_kwargs: dict[str, object] = {"parsing_strategy": parsing_strategy}

        if parsing_strategy == "BEDROCK_FOUNDATION_MODEL":
            if not advanced_parsing_model_arn:
                raise ValueError(
                    "advanced_parsing_strategy=BEDROCK_FOUNDATION_MODEL requires "
                    "advanced_parsing_model_arn (context: advancedParsingModelArn)"
                )
            fm_cfg_kwargs: dict[str, object] = {"model_arn": advanced_parsing_model_arn}
            if advanced_parsing_modality:
                fm_cfg_kwargs["parsing_modality"] = advanced_parsing_modality
            parsing_configuration_kwargs["bedrock_foundation_model_configuration"] = (
                bedrock.CfnDataSource.BedrockFoundationModelConfigurationProperty(**fm_cfg_kwargs)
            )
        elif parsing_strategy == "BEDROCK_DATA_AUTOMATION":
            # Bedrock rejects an empty BedrockDataAutomationConfiguration object.
            # Default to MULTIMODAL when the modality is not explicitly provided.
            modality = (advanced_parsing_modality or "MULTIMODAL").strip().upper()
            bda_kwargs: dict[str, object] = {"parsing_modality": modality}
            parsing_configuration_kwargs["bedrock_data_automation_configuration"] = (
                bedrock.CfnDataSource.BedrockDataAutomationConfigurationProperty(**bda_kwargs)
            )
        else:
            raise ValueError(
                "advanced_parsing_strategy must be BEDROCK_FOUNDATION_MODEL or "
                "BEDROCK_DATA_AUTOMATION"
            )

        return bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
            parsing_configuration=bedrock.CfnDataSource.ParsingConfigurationProperty(
                **parsing_configuration_kwargs
            )
        )

    @staticmethod
    def _normalize_s3vectors_index_name(value: str) -> str:
        # S3 Vectors index names are stricter than generic Bedrock resource names.
        # Keep only lowercase alnum/hyphen and enforce a practical bounded length.
        normalized = re.sub(r"[^a-z0-9-]", "-", value.strip().lower())
        normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
        if not normalized:
            normalized = "evidentia-index"
        if not normalized[0].isalnum():
            normalized = f"idx-{normalized}"
        normalized = normalized[:63].strip("-")
        if len(normalized) < 3:
            normalized = (normalized + "-ix")[:3]
        return normalized

    def _default_bedrock_resource_name(
        self,
        *,
        suffix: str,
        stage_name: str,
        fingerprint_seed: str,
    ) -> str:
        # Bedrock resources require a name at this CDK version.
        # Include a deterministic fingerprint so replacements can adopt a new
        # physical name when configuration changes.
        stack_part = self._normalize_bedrock_name_token(self.stack_name, max_len=65)
        suffix_part = self._normalize_bedrock_name_token(suffix, max_len=20)
        fingerprint = hashlib.sha1(fingerprint_seed.encode("utf-8")).hexdigest()[:8]
        name = f"{stack_part}-{suffix_part}-{fingerprint}"
        return name[:100].strip("-")

    @staticmethod
    def _normalize_bedrock_name_token(value: str, *, max_len: int) -> str:
        normalized = re.sub(r"[^0-9A-Za-z-]", "-", value).strip("-")
        normalized = re.sub(r"-{2,}", "-", normalized)
        if not normalized:
            normalized = "evidentia"
        return normalized[:max_len]

    def _default_s3vectors_index_name(
        self,
        *,
        stage_name: str,
        data_type: str,
        dimension: int,
        distance_metric: str,
        non_filterable_metadata_keys: tuple[str, ...],
    ) -> str:
        stage_part = self._normalize_s3vectors_index_name(stage_name)
        fingerprint_input = "|".join(
            [
                self.stack_name,
                stage_name,
                data_type.lower(),
                str(dimension),
                distance_metric.lower(),
                ",".join(non_filterable_metadata_keys),
            ]
        )
        fingerprint = hashlib.sha1(fingerprint_input.encode("utf-8")).hexdigest()[:8]
        candidate = f"evidentia-{stage_part}-index-{fingerprint}"
        return self._normalize_s3vectors_index_name(candidate)

    def _emit_outputs(
        self,
        *,
        raw_bucket: s3.Bucket,
        assets_bucket: s3.Bucket,
        vectors_bucket: s3vectors.CfnVectorBucket,
        vectors_index: s3vectors.CfnIndex,
        ingestion_manifest_table: dynamodb.Table,
        kb_role: iam.Role,
        api_role: iam.Role,
        stage_name: str,
        kb_resource: bedrock.CfnKnowledgeBase | None,
        data_source_resource: bedrock.CfnDataSource | None,
    ) -> None:
        outputs = {
            "StageName": stage_name,
            "RawBucketName": raw_bucket.bucket_name,
            "RawBucketArn": raw_bucket.bucket_arn,
            "AssetsBucketName": assets_bucket.bucket_name,
            "AssetsBucketArn": assets_bucket.bucket_arn,
            "VectorsBucketName": vectors_bucket.ref,
            "VectorsBucketArn": vectors_bucket.attr_vector_bucket_arn,
            "S3VectorsIndexName": vectors_index.ref,
            "S3VectorsIndexArn": vectors_index.attr_index_arn,
            "RawPrefixTemplate": f"{RAW_PREFIX}/{{doc_id}}/source.pdf",
            "AssetsPrefixTemplate": BEDROCK_ASSETS_PREFIX_TEMPLATE,
            "IngestionManifestTableName": ingestion_manifest_table.table_name,
            "IngestionManifestTableArn": ingestion_manifest_table.table_arn,
            "IngestionManifestSourceUriIndexName": INGESTION_MANIFEST_SOURCE_URI_INDEX_NAME,
            "KnowledgeBaseRoleArn": kb_role.role_arn,
            "ApiRuntimeRoleArn": api_role.role_arn,
        }
        if kb_resource is not None:
            outputs["BedrockKnowledgeBaseId"] = kb_resource.attr_knowledge_base_id
            outputs["BedrockKnowledgeBaseArn"] = kb_resource.attr_knowledge_base_arn
        if data_source_resource is not None:
            outputs["BedrockKnowledgeBaseDataSourceId"] = data_source_resource.attr_data_source_id
        for key, value in outputs.items():
            CfnOutput(self, key, value=value)
