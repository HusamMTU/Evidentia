from __future__ import annotations

from dataclasses import dataclass

from aws_cdk import (
    CfnOutput,
    CfnDeletionPolicy,
    Duration,
    RemovalPolicy,
    Stack,
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3vectors as s3vectors,
)
from constructs import Construct


RAW_PREFIX = "documents-raw"
ASSETS_PREFIX = "documents-assets"


@dataclass(frozen=True)
class FoundationStackProps:
    stage_name: str
    raw_bucket_name: str | None = None
    assets_bucket_name: str | None = None
    vectors_bucket_name: str | None = None
    api_runtime_principal: str = "lambda.amazonaws.com"
    enable_bedrock_kb: bool = False
    knowledge_base_name: str | None = None
    knowledge_base_data_source_name: str | None = None
    embedding_model_arn: str | None = None
    s3_vectors_index_name: str | None = None
    s3_vectors_data_type: str = "float32"
    s3_vectors_dimension: int = 1024
    s3_vectors_distance_metric: str = "cosine"
    advanced_parsing_strategy: str | None = None
    advanced_parsing_model_arn: str | None = None
    advanced_parsing_modality: str | None = None


class EvidentiaFoundationStack(Stack):
    """Phase 1 foundation resources for Evidentia.

    This stack intentionally focuses on storage + IAM first. Bedrock Knowledge Base
    resources are added in a follow-up once CDK/CloudFormation support is pinned
    for the target account/region and S3 Vectors configuration shape is confirmed.
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
        api_runtime_principal: str = "lambda.amazonaws.com",
        enable_bedrock_kb: bool = False,
        knowledge_base_name: str | None = None,
        knowledge_base_data_source_name: str | None = None,
        embedding_model_arn: str | None = None,
        s3_vectors_index_name: str | None = None,
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
            api_runtime_principal=api_runtime_principal,
            enable_bedrock_kb=enable_bedrock_kb,
            knowledge_base_name=knowledge_base_name,
            knowledge_base_data_source_name=knowledge_base_data_source_name,
            embedding_model_arn=embedding_model_arn,
            s3_vectors_index_name=s3_vectors_index_name,
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
            data_type=props.s3_vectors_data_type,
            dimension=props.s3_vectors_dimension,
            distance_metric=props.s3_vectors_distance_metric,
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

        effective_index_name = index_name or f"evidentia-{stage_name}-index"
        vector_index = s3vectors.CfnIndex(
            self,
            "S3VectorsIndex",
            data_type=data_type.lower(),
            dimension=dimension,
            distance_metric=distance_metric.lower(),
            index_name=effective_index_name,
            vector_bucket_arn=vector_bucket.attr_vector_bucket_arn,
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
        role.add_to_policy(
            iam.PolicyStatement(
                sid="S3VectorsPermissions",
                actions=["s3vectors:*"],
                resources=[vectors_bucket.attr_vector_bucket_arn, vectors_index.attr_index_arn],
            )
        )

        return role

    def _create_api_role(self, *, assets_bucket: s3.Bucket, api_runtime_principal: str) -> iam.Role:
        role = iam.Role(
            self,
            "ApiRuntimeRole",
            assumed_by=iam.ServicePrincipal(api_runtime_principal),
            description="API runtime role for Evidentia query retrieval, asset presigning, and Claude invocation.",
        )

        assets_bucket.grant_read(role)

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
        kb_name = knowledge_base_name or f"evidentia-kb-{stage_name}"
        ds_name = knowledge_base_data_source_name or f"evidentia-raw-s3-{stage_name}"
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

        knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "BedrockKnowledgeBase",
            name=kb_name,
            role_arn=kb_role.role_arn,
            description="Evidentia multimodal grounded document intelligence knowledge base.",
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    **vector_kb_config_kwargs
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    vector_bucket_arn=vectors_bucket.attr_vector_bucket_arn,
                    index_arn=vectors_index.attr_index_arn,
                ),
            ),
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

    def _emit_outputs(
        self,
        *,
        raw_bucket: s3.Bucket,
        assets_bucket: s3.Bucket,
        vectors_bucket: s3vectors.CfnVectorBucket,
        vectors_index: s3vectors.CfnIndex,
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
            "AssetsPrefixTemplate": f"{ASSETS_PREFIX}/{{doc_id}}/{{asset_id}}.png",
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
