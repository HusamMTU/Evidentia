#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from provenance import (  # noqa: E402
    DynamoIngestionManifestStore,
    IngestionManifestRecord,
    SOURCE_URI_INDEX_NAME,
    make_s3_uri,
)


DEFAULT_STACK_NAME = "EvidentiaFoundation-dev"
DEFAULT_MANIFEST = REPO_ROOT / "datasets" / "seed_corpus" / "manifest.csv"
DEFAULT_REPORTS_DIR = REPO_ROOT / "datasets" / "seed_corpus" / "reports" / "generated"
REQUIRED_COLUMNS = {"doc_id", "source_path", "ingestion_status"}
SUMMARY_INTEGER_KEYS = {
    "scanned",
    "new",
    "modified",
    "failed",
    "legacy_assets_key_count_total",
    "bedrock_assets_key_count",
    "assets_key_count_total",
    "expected_documents",
}


@dataclass(frozen=True)
class BatchConfig:
    stack_name: str
    region: str
    profile: str | None
    raw_bucket: str
    assets_bucket: str
    kb_id: str
    data_source_id: str
    manifest_table_name: str | None
    manifest_source_uri_index_name: str
    poll_seconds: int
    timeout_seconds: int


@dataclass(frozen=True)
class StagedDocument:
    row: dict[str, str]
    source_path: Path
    source_uri: str
    source_etag: str | None
    source_version_id: str | None

    @property
    def doc_id(self) -> str:
        return self.row["doc_id"].strip()

    @property
    def doc_type(self) -> str:
        return self.row.get("doc_type", "")

    @property
    def prior_status(self) -> str:
        return self.row.get("ingestion_status", "")


class BatchLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def line(self, message: str = "") -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(message)
            handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage selected seed documents, run one Bedrock ingestion job, and update the manifest."
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to the seed corpus manifest CSV.",
    )
    parser.add_argument(
        "--doc-id",
        action="append",
        dest="doc_ids",
        help="Restrict ingestion to specific doc_id values. May be repeated.",
    )
    parser.add_argument(
        "--status",
        action="append",
        dest="statuses",
        help="Restrict ingestion to specific ingestion_status values. May be repeated. Defaults to 'planned'.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of manifest rows to process after filtering.",
    )
    parser.add_argument(
        "--report-path",
        help="Path to the JSONL report to write. Defaults under datasets/seed_corpus/reports/generated/.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop staging after the first document failure instead of continuing through the selection.",
    )
    parser.add_argument(
        "--skip-manifest-update",
        action="store_true",
        help="Do not rewrite manifest ingestion_status values in manifest.csv.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the selected documents and staged object keys without running AWS operations.",
    )

    parser.add_argument("--stack-name", default=DEFAULT_STACK_NAME)
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"))
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE"))
    parser.add_argument("--raw-bucket", default=os.getenv("EVIDENTIA_RAW_BUCKET"))
    parser.add_argument("--assets-bucket", default=os.getenv("EVIDENTIA_ASSETS_BUCKET"))
    parser.add_argument("--kb-id", default=os.getenv("BEDROCK_KNOWLEDGE_BASE_ID"))
    parser.add_argument("--data-source-id", default=os.getenv("BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_ID"))
    parser.add_argument("--kb-name", default=os.getenv("BEDROCK_KNOWLEDGE_BASE_NAME"))
    parser.add_argument("--data-source-name", default=os.getenv("BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_NAME"))
    parser.add_argument(
        "--manifest-table-name",
        default=os.getenv("EVIDENTIA_INGESTION_MANIFEST_TABLE_NAME"),
    )
    parser.add_argument(
        "--manifest-source-uri-index-name",
        default=os.getenv("EVIDENTIA_INGESTION_MANIFEST_SOURCE_URI_INDEX", SOURCE_URI_INDEX_NAME),
    )
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--allow-multiple-data-sources",
        action="store_true",
        help="Allow ingestion to continue even when the knowledge base has multiple active data sources.",
    )
    parser.add_argument(
        "--skip-manifest-write",
        action="store_true",
        help="Skip DynamoDB ingestion manifest writes while still updating the local CSV report.",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - set(fieldnames)
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise SystemExit(f"Manifest is missing required columns: {missing_list}")
        rows = [dict(row) for row in reader]
    return fieldnames, rows


def write_manifest(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)


def normalize_status_filters(values: list[str] | None) -> set[str]:
    raw_values = values if values else ["planned"]
    normalized: set[str] = set()
    for value in raw_values:
        for part in value.split(","):
            cleaned = part.strip()
            if cleaned:
                normalized.add(cleaned)
    return normalized


def select_rows(
    rows: list[dict[str, str]],
    *,
    doc_ids: list[str] | None,
    statuses: set[str],
    limit: int | None,
) -> list[dict[str, str]]:
    requested_ids = {value.strip() for value in (doc_ids or []) if value.strip()}
    if requested_ids:
        known_ids = {row.get("doc_id", "").strip() for row in rows}
        missing_ids = sorted(requested_ids - known_ids)
        if missing_ids:
            raise SystemExit(f"Unknown doc_id values: {', '.join(missing_ids)}")

    selected: list[dict[str, str]] = []
    for row in rows:
        doc_id = row.get("doc_id", "").strip()
        status = row.get("ingestion_status", "").strip()
        if requested_ids and doc_id not in requested_ids:
            continue
        if status not in statuses:
            continue
        selected.append(row)
        if limit is not None and len(selected) >= limit:
            break

    if not selected:
        raise SystemExit("No manifest rows matched the requested filters.")
    return selected


def default_report_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_REPORTS_DIR / f"seed_ingestion_{timestamp}.jsonl"


def log_directory_for_report(report_path: Path) -> Path:
    return report_path.parent / f"{report_path.stem}_logs"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def source_file_path(row: dict[str, str]) -> Path:
    return (REPO_ROOT / row["source_path"].strip()).resolve()


def source_object_key(doc_id: str, source_path: Path) -> str:
    suffix = "".join(source_path.suffixes)
    filename = f"source{suffix}" if suffix else "source"
    return f"documents-raw/{doc_id}/" + filename


def update_row_status(
    row: dict[str, str],
    status: str,
    *,
    manifest_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
    skip_manifest_update: bool,
) -> None:
    row["ingestion_status"] = status
    if not skip_manifest_update:
        write_manifest(manifest_path, fieldnames, rows)


def write_report_entry(report_path: Path, entry: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def tail_text(output: str, *, lines: int = 20) -> str:
    selected = output.strip().splitlines()[-lines:]
    return "\n".join(selected)


def normalize_aws_text(value: str | None) -> str | None:
    if value is None:
        return None
    lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    if not lines:
        return None
    if all(line == "None" for line in lines):
        return None
    return "\n".join(lines)


def integer_summary(value: Any) -> int:
    if value in (None, "", "None"):
        return 0
    return int(value)


def aws_base_command(config: BatchConfig, *parts: str) -> list[str]:
    command = ["aws", "--region", config.region]
    if config.profile:
        command.extend(["--profile", config.profile])
    command.extend(parts)
    return command


def run_command(
    command: list[str],
    *,
    logger: BatchLogger,
    description: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    logger.line(f"$ {shlex.join(command)}")
    process = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if process.stdout:
        for line in process.stdout.rstrip().splitlines():
            logger.line(line)
    if check and process.returncode != 0:
        excerpt = tail_text(process.stdout or "")
        raise RuntimeError(f"{description} failed with exit_code={process.returncode}\n{excerpt}")
    return process


def run_aws_text(
    config: BatchConfig,
    *parts: str,
    logger: BatchLogger,
    description: str,
    check: bool = True,
) -> str:
    process = run_command(
        aws_base_command(config, *parts),
        logger=logger,
        description=description,
        check=check,
    )
    return process.stdout.strip()


def run_aws_json(
    config: BatchConfig,
    *parts: str,
    logger: BatchLogger,
    description: str,
    check: bool = True,
) -> dict[str, Any]:
    output = run_aws_text(config, *parts, logger=logger, description=description, check=check)
    if not output:
        return {}
    return json.loads(output)


def get_stack_output(
    *,
    stack_name: str,
    region: str,
    profile: str | None,
    output_key: str,
    logger: BatchLogger,
) -> str | None:
    config = BatchConfig(
        stack_name=stack_name,
        region=region,
        profile=profile,
        raw_bucket="",
        assets_bucket="",
        kb_id="",
        data_source_id="",
        manifest_table_name=None,
        manifest_source_uri_index_name=SOURCE_URI_INDEX_NAME,
        poll_seconds=15,
        timeout_seconds=1800,
    )
    command = aws_base_command(
        config,
        "cloudformation",
        "describe-stacks",
        "--stack-name",
        stack_name,
        "--query",
        f"Stacks[0].Outputs[?OutputKey=='{output_key}'].OutputValue | [0]",
        "--output",
        "text",
    )
    process = run_command(command, logger=logger, description=f"resolve stack output {output_key}", check=False)
    if process.returncode != 0:
        return None
    return normalize_aws_text(process.stdout)


def resolve_runtime_config(args: argparse.Namespace, logger: BatchLogger) -> BatchConfig:
    region = normalize_aws_text(args.region)
    if not region:
        raise SystemExit("Region is required. Set AWS_REGION/AWS_DEFAULT_REGION or pass --region.")

    stack_name = args.stack_name or DEFAULT_STACK_NAME
    profile = normalize_aws_text(args.profile)
    raw_bucket = normalize_aws_text(args.raw_bucket) or get_stack_output(
        stack_name=stack_name,
        region=region,
        profile=profile,
        output_key="RawBucketName",
        logger=logger,
    )
    assets_bucket = normalize_aws_text(args.assets_bucket) or get_stack_output(
        stack_name=stack_name,
        region=region,
        profile=profile,
        output_key="AssetsBucketName",
        logger=logger,
    )
    kb_id = normalize_aws_text(args.kb_id) or get_stack_output(
        stack_name=stack_name,
        region=region,
        profile=profile,
        output_key="BedrockKnowledgeBaseId",
        logger=logger,
    )
    data_source_id = normalize_aws_text(args.data_source_id) or get_stack_output(
        stack_name=stack_name,
        region=region,
        profile=profile,
        output_key="BedrockKnowledgeBaseDataSourceId",
        logger=logger,
    )
    manifest_table_name = normalize_aws_text(args.manifest_table_name)
    if not args.skip_manifest_write and not manifest_table_name:
        manifest_table_name = get_stack_output(
            stack_name=stack_name,
            region=region,
            profile=profile,
            output_key="IngestionManifestTableName",
            logger=logger,
        )
    manifest_source_uri_index_name = (
        normalize_aws_text(args.manifest_source_uri_index_name)
        or get_stack_output(
            stack_name=stack_name,
            region=region,
            profile=profile,
            output_key="IngestionManifestSourceUriIndexName",
            logger=logger,
        )
        or SOURCE_URI_INDEX_NAME
    )

    missing = []
    if not raw_bucket:
        missing.append("raw bucket")
    if not assets_bucket:
        missing.append("assets bucket")
    if not kb_id:
        missing.append("knowledge base ID")
    if not data_source_id:
        missing.append("data source ID")
    if not args.skip_manifest_write and not manifest_table_name:
        missing.append("ingestion manifest table name")
    if missing:
        raise SystemExit(
            "Unable to resolve required AWS configuration: " + ", ".join(missing) + ". "
            "Set them in .env, pass flags explicitly, or expose the matching stack outputs."
        )

    config = BatchConfig(
        stack_name=stack_name,
        region=region,
        profile=profile,
        raw_bucket=raw_bucket,
        assets_bucket=assets_bucket,
        kb_id=kb_id,
        data_source_id=data_source_id,
        manifest_table_name=manifest_table_name,
        manifest_source_uri_index_name=manifest_source_uri_index_name,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    validate_active_data_sources(config, allow_multiple=args.allow_multiple_data_sources, logger=logger)
    return config


def validate_active_data_sources(
    config: BatchConfig,
    *,
    allow_multiple: bool,
    logger: BatchLogger,
) -> None:
    if allow_multiple:
        return
    payload = run_aws_json(
        config,
        "bedrock-agent",
        "list-data-sources",
        "--knowledge-base-id",
        config.kb_id,
        "--output",
        "json",
        logger=logger,
        description="list active data sources",
    )
    summaries = payload.get("dataSourceSummaries", [])
    active = [
        item
        for item in summaries
        if item.get("status") in {"AVAILABLE", "ACTIVE"} and item.get("dataSourceId")
    ]
    if len(active) > 1:
        formatted = ", ".join(
            f"{item.get('dataSourceId')}:{item.get('name', '')}:{item.get('status', '')}"
            for item in active
        )
        raise SystemExit(
            "Knowledge base has multiple active data sources; refusing to continue. "
            "Pass --allow-multiple-data-sources to bypass. Active sources: "
            + formatted
        )


def build_manifest_store(config: BatchConfig) -> DynamoIngestionManifestStore:
    assert config.manifest_table_name
    try:
        return DynamoIngestionManifestStore(
            config.manifest_table_name,
            region_name=config.region,
            source_uri_index_name=config.manifest_source_uri_index_name,
        )
    except RuntimeError as exc:
        raise SystemExit(
            f"{exc}\nRun this script with the repo virtualenv, for example: ./.venv/bin/python {Path(__file__).name}"
        ) from exc


def upsert_manifest_record(
    store: DynamoIngestionManifestStore,
    *,
    doc_id: str,
    source_uri: str,
    status: str,
    config: BatchConfig,
    source_etag: str | None = None,
    source_version_id: str | None = None,
    ingestion_job_id: str | None = None,
    logger: BatchLogger,
) -> None:
    logger.line(
        f"manifest upsert: doc_id={doc_id} status={status} source_uri={source_uri}"
        + (f" ingestion_job_id={ingestion_job_id}" if ingestion_job_id else "")
    )
    record = IngestionManifestRecord.from_doc_and_uri(
        doc_id=doc_id,
        source_uri=source_uri,
        status=status,
        kb_id=config.kb_id,
        data_source_id=config.data_source_id,
        ingestion_job_id=ingestion_job_id,
        source_etag=source_etag,
        source_version_id=source_version_id,
    )
    store.upsert(record)


def stage_document(
    row: dict[str, str],
    *,
    config: BatchConfig,
    store: DynamoIngestionManifestStore | None,
    logger: BatchLogger,
) -> StagedDocument:
    doc_id = row["doc_id"].strip()
    source_path = source_file_path(row)
    if not source_path.exists():
        raise FileNotFoundError(
            f"Source file not found: {source_path}\nRun scripts/fetch_seed_corpus.py before batch ingestion."
        )

    raw_key = source_object_key(doc_id, source_path)
    source_uri = make_s3_uri(config.raw_bucket, raw_key)

    logger.line(f"staging doc_id={doc_id} source={source_path}")
    run_command(
        ["aws", "--region", config.region]
        + (["--profile", config.profile] if config.profile else [])
        + ["s3", "cp", str(source_path), source_uri],
        logger=logger,
        description=f"upload {doc_id}",
    )
    head_object = run_aws_json(
        config,
        "s3api",
        "head-object",
        "--bucket",
        config.raw_bucket,
        "--key",
        raw_key,
        "--query",
        "{etag: ETag, version_id: VersionId}",
        "--output",
        "json",
        logger=logger,
        description=f"head raw object for {doc_id}",
    )
    source_etag = normalize_aws_text(head_object.get("etag"))
    source_version_id = normalize_aws_text(head_object.get("version_id"))

    if store is not None:
        upsert_manifest_record(
            store,
            doc_id=doc_id,
            source_uri=source_uri,
            status="uploaded",
            config=config,
            source_etag=source_etag,
            source_version_id=source_version_id,
            logger=logger,
        )

    return StagedDocument(
        row=row,
        source_path=source_path,
        source_uri=source_uri,
        source_etag=source_etag,
        source_version_id=source_version_id,
    )


def batch_description(doc_ids: list[str]) -> str:
    preview = ", ".join(doc_ids[:3])
    remainder = len(doc_ids) - 3
    if remainder > 0:
        preview += f" (+{remainder} more)"
    return f"Seed corpus batch ingestion for {len(doc_ids)} docs: {preview}"


def start_ingestion_job(
    config: BatchConfig,
    *,
    doc_ids: list[str],
    logger: BatchLogger,
) -> str:
    description = batch_description(doc_ids)
    ingestion_job_id = normalize_aws_text(
        run_aws_text(
            config,
            "bedrock-agent",
            "start-ingestion-job",
            "--knowledge-base-id",
            config.kb_id,
            "--data-source-id",
            config.data_source_id,
            "--description",
            description,
            "--query",
            "ingestionJob.ingestionJobId",
            "--output",
            "text",
            logger=logger,
            description="start Bedrock ingestion job",
        )
    )
    if not ingestion_job_id:
        raise RuntimeError("Failed to start ingestion job.")
    logger.line(f"ingestion job started: {ingestion_job_id}")
    return ingestion_job_id


def get_ingestion_job_snapshot(
    config: BatchConfig,
    *,
    ingestion_job_id: str,
    logger: BatchLogger,
) -> dict[str, Any]:
    payload = run_aws_json(
        config,
        "bedrock-agent",
        "get-ingestion-job",
        "--knowledge-base-id",
        config.kb_id,
        "--data-source-id",
        config.data_source_id,
        "--ingestion-job-id",
        ingestion_job_id,
        "--query",
        (
            "ingestionJob.{status: status, "
            "scanned: statistics.numberOfDocumentsScanned, "
            "new: statistics.numberOfNewDocumentsIndexed, "
            "modified: statistics.numberOfModifiedDocumentsIndexed, "
            "failed: statistics.numberOfDocumentsFailed, "
            "failure_reasons: failureReasons}"
        ),
        "--output",
        "json",
        logger=logger,
        description=f"get ingestion job {ingestion_job_id}",
    )
    return {
        "final_status": payload.get("status", ""),
        "scanned": integer_summary(payload.get("scanned")),
        "new": integer_summary(payload.get("new")),
        "modified": integer_summary(payload.get("modified")),
        "failed": integer_summary(payload.get("failed")),
        "failure_reasons": payload.get("failure_reasons") or [],
    }


def poll_ingestion_job(
    config: BatchConfig,
    *,
    ingestion_job_id: str,
    logger: BatchLogger,
) -> dict[str, Any]:
    logger.line("polling ingestion job status")
    started_epoch = time.time()
    while True:
        summary = get_ingestion_job_snapshot(config, ingestion_job_id=ingestion_job_id, logger=logger)
        elapsed = int(time.time() - started_epoch)
        logger.line(
            "  - status="
            f"{summary['final_status']} elapsed={elapsed}s scanned={summary['scanned']} "
            f"new={summary['new']} modified={summary['modified']} failed={summary['failed']}"
        )
        if summary["final_status"] in {"COMPLETE", "FAILED", "STOPPED"}:
            summary["elapsed_seconds"] = elapsed
            return summary
        if elapsed >= config.timeout_seconds:
            raise RuntimeError(
                f"Timed out after {config.timeout_seconds}s waiting for ingestion job {ingestion_job_id}."
            )
        time.sleep(config.poll_seconds)


def count_s3_prefix(
    config: BatchConfig,
    *,
    bucket: str,
    prefix: str,
    logger: BatchLogger,
) -> int:
    value = normalize_aws_text(
        run_aws_text(
            config,
            "s3api",
            "list-objects-v2",
            "--bucket",
            bucket,
            "--prefix",
            prefix,
            "--query",
            "KeyCount",
            "--output",
            "text",
            logger=logger,
            description=f"list objects for s3://{bucket}/{prefix}",
        )
    )
    return integer_summary(value)


def collect_asset_summary(
    config: BatchConfig,
    *,
    staged_documents: list[StagedDocument],
    logger: BatchLogger,
) -> tuple[dict[str, Any], dict[str, int]]:
    legacy_counts: dict[str, int] = {}
    legacy_total = 0
    for staged in staged_documents:
        prefix = f"documents-assets/{staged.doc_id}/"
        count = count_s3_prefix(config, bucket=config.assets_bucket, prefix=prefix, logger=logger)
        legacy_counts[staged.doc_id] = count
        legacy_total += count
        logger.line(f"legacy assets: doc_id={staged.doc_id} count={count}")

    bedrock_prefix = f"aws/bedrock/knowledge_bases/{config.kb_id}/{config.data_source_id}/"
    bedrock_count = count_s3_prefix(
        config,
        bucket=config.assets_bucket,
        prefix=bedrock_prefix,
        logger=logger,
    )
    logger.line(f"bedrock-managed assets under {bedrock_prefix}: {bedrock_count}")
    return (
        {
            "legacy_assets_key_count_total": legacy_total,
            "bedrock_assets_key_count": bedrock_count,
            "assets_key_count_total": legacy_total + bedrock_count,
        },
        legacy_counts,
    )


def assess_batch_summary(summary: dict[str, Any], *, expected_documents: int) -> str | None:
    final_status = summary.get("final_status", "")
    if final_status != "COMPLETE":
        reasons = summary.get("failure_reasons") or []
        details = f" Reasons: {', '.join(str(item) for item in reasons)}" if reasons else ""
        return f"Ingestion job ended with status {final_status}.{details}"

    failed_documents = integer_summary(summary.get("failed"))
    if failed_documents > 0:
        reasons = summary.get("failure_reasons") or []
        details = f" Failure reasons: {', '.join(str(item) for item in reasons)}" if reasons else ""
        return f"Ingestion completed with failed={failed_documents}.{details}"

    indexed_total = integer_summary(summary.get("new")) + integer_summary(summary.get("modified"))
    if indexed_total < expected_documents:
        return (
            f"Ingestion completed but indexed_total={indexed_total}. "
            f"Expected at least {expected_documents} indexed/updated documents for the staged batch."
        )
    return None


def build_failure_entry(
    row: dict[str, str],
    *,
    started_at: datetime,
    completed_at: datetime,
    source_path: Path,
    batch_log_path: Path,
    error_excerpt: str,
) -> dict[str, Any]:
    return {
        "doc_id": row["doc_id"].strip(),
        "doc_type": row.get("doc_type", ""),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
        "source_path": display_path(source_path),
        "log_path": display_path(batch_log_path),
        "success": False,
        "exit_code": 1,
        "ingestion_status_before": row.get("ingestion_status", ""),
        "ingestion_status_after": "failed",
        "summary": {},
        "error_excerpt": error_excerpt.strip(),
    }


def build_success_or_batch_failure_entry(
    staged: StagedDocument,
    *,
    batch_started_at: datetime,
    batch_completed_at: datetime,
    batch_log_path: Path,
    summary: dict[str, Any],
    legacy_asset_count: int,
    ingestion_status_after: str,
    error_excerpt: str | None,
) -> dict[str, Any]:
    row_summary = dict(summary)
    row_summary["legacy_assets_key_count_for_doc"] = legacy_asset_count

    entry = {
        "doc_id": staged.doc_id,
        "doc_type": staged.doc_type,
        "started_at": batch_started_at.isoformat(),
        "completed_at": batch_completed_at.isoformat(),
        "duration_seconds": round((batch_completed_at - batch_started_at).total_seconds(), 3),
        "source_path": display_path(staged.source_path),
        "source_uri": staged.source_uri,
        "log_path": display_path(batch_log_path),
        "success": ingestion_status_after == "verified",
        "exit_code": 0 if ingestion_status_after == "verified" else 1,
        "ingestion_status_before": staged.prior_status,
        "ingestion_status_after": ingestion_status_after,
        "summary": row_summary,
    }
    if error_excerpt:
        entry["error_excerpt"] = error_excerpt
    return entry


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    report_path = Path(args.report_path).resolve() if args.report_path else default_report_path()
    logs_dir = log_directory_for_report(report_path)
    batch_log_path = logs_dir / "batch.log"

    fieldnames, rows = load_manifest(manifest_path)
    statuses = normalize_status_filters(args.statuses)
    selected_rows = select_rows(rows, doc_ids=args.doc_ids, statuses=statuses, limit=args.limit)

    if args.dry_run:
        print(f"Selected {len(selected_rows)} documents from {manifest_path}:")
        for row in selected_rows:
            doc_id = row["doc_id"].strip()
            source_path = source_file_path(row)
            raw_key = source_object_key(doc_id, source_path)
            print(f"  - {doc_id} [{row.get('ingestion_status', '')}] -> {display_path(source_path)}")
            print(f"    staged object key: {raw_key}")
        print("Batch behavior: upload selected documents, start one shared ingestion job, then evaluate the batch as a whole.")
        print(f"Report would be written to: {report_path}")
        return

    report_path.parent.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = BatchLogger(batch_log_path)
    logger.line("Seed corpus batch ingestion")
    logger.line(f"manifest={manifest_path}")
    logger.line(f"report={report_path}")
    logger.line(f"selected_docs={len(selected_rows)}")

    config = resolve_runtime_config(args, logger)
    logger.line(
        f"resolved config: region={config.region} raw_bucket={config.raw_bucket} "
        f"assets_bucket={config.assets_bucket} kb_id={config.kb_id} data_source_id={config.data_source_id}"
    )

    store = None if args.skip_manifest_write else build_manifest_store(config)

    processed = 0
    failures = 0
    staged_documents: list[StagedDocument] = []
    batch_started_at = datetime.now(timezone.utc)

    for row in selected_rows:
        processed += 1
        doc_id = row["doc_id"].strip()
        print(f"[{processed}/{len(selected_rows)}] staging {doc_id}")
        started_at = datetime.now(timezone.utc)
        try:
            staged = stage_document(row, config=config, store=store, logger=logger)
        except Exception as exc:
            failures += 1
            completed_at = datetime.now(timezone.utc)
            error_excerpt = str(exc)
            entry = build_failure_entry(
                row,
                started_at=started_at,
                completed_at=completed_at,
                source_path=source_file_path(row),
                batch_log_path=batch_log_path,
                error_excerpt=error_excerpt,
            )
            write_report_entry(report_path, entry)
            update_row_status(
                row,
                "failed",
                manifest_path=manifest_path,
                fieldnames=fieldnames,
                rows=rows,
                skip_manifest_update=args.skip_manifest_update,
            )
            print(f"  FAIL {error_excerpt}", file=sys.stderr)
            if args.fail_fast:
                break
            continue

        staged_documents.append(staged)
        update_row_status(
            row,
            "uploaded",
            manifest_path=manifest_path,
            fieldnames=fieldnames,
            rows=rows,
            skip_manifest_update=args.skip_manifest_update,
        )
        print(f"  STAGED {staged.source_uri}")

    if not staged_documents:
        print(f"Done. processed={processed} failures={failures} report={display_path(report_path)}")
        raise SystemExit(1 if failures else 0)

    if args.fail_fast and failures:
        print(
            f"Done. processed={processed} staged={len(staged_documents)} failures={failures} "
            f"report={display_path(report_path)}"
        )
        raise SystemExit(1)

    ingestion_job_id: str | None = None
    summary: dict[str, Any] = {}
    legacy_asset_counts: dict[str, int] = {doc.doc_id: 0 for doc in staged_documents}
    batch_error: str | None = None
    manifest_status = "ingested"

    try:
        print(f"Starting shared ingestion job for {len(staged_documents)} staged documents")
        ingestion_job_id = start_ingestion_job(
            config,
            doc_ids=[staged.doc_id for staged in staged_documents],
            logger=logger,
        )
        for staged in staged_documents:
            if store is not None:
                upsert_manifest_record(
                    store,
                    doc_id=staged.doc_id,
                    source_uri=staged.source_uri,
                    status="ingestion_started",
                    config=config,
                    source_etag=staged.source_etag,
                    source_version_id=staged.source_version_id,
                    ingestion_job_id=ingestion_job_id,
                    logger=logger,
                )
            update_row_status(
                staged.row,
                "ingestion_started",
                manifest_path=manifest_path,
                fieldnames=fieldnames,
                rows=rows,
                skip_manifest_update=args.skip_manifest_update,
            )

        summary = poll_ingestion_job(config, ingestion_job_id=ingestion_job_id, logger=logger)
        asset_summary, legacy_asset_counts = collect_asset_summary(
            config,
            staged_documents=staged_documents,
            logger=logger,
        )
        summary.update(asset_summary)
        summary["ingestion_job_id"] = ingestion_job_id
        summary["expected_documents"] = len(staged_documents)
        batch_error = assess_batch_summary(summary, expected_documents=len(staged_documents))
        if batch_error:
            manifest_status = "ingestion_failed"
    except Exception as exc:
        batch_error = str(exc)
        manifest_status = "ingestion_failed"

    batch_completed_at = datetime.now(timezone.utc)
    final_local_status = "verified" if batch_error is None else "failed"

    for staged in staged_documents:
        if store is not None:
            upsert_manifest_record(
                store,
                doc_id=staged.doc_id,
                source_uri=staged.source_uri,
                status=manifest_status,
                config=config,
                source_etag=staged.source_etag,
                source_version_id=staged.source_version_id,
                ingestion_job_id=ingestion_job_id,
                logger=logger,
            )
        update_row_status(
            staged.row,
            final_local_status,
            manifest_path=manifest_path,
            fieldnames=fieldnames,
            rows=rows,
            skip_manifest_update=args.skip_manifest_update,
        )

        entry = build_success_or_batch_failure_entry(
            staged,
            batch_started_at=batch_started_at,
            batch_completed_at=batch_completed_at,
            batch_log_path=batch_log_path,
            summary=summary,
            legacy_asset_count=legacy_asset_counts.get(staged.doc_id, 0),
            ingestion_status_after=final_local_status,
            error_excerpt=batch_error,
        )
        write_report_entry(report_path, entry)

    if batch_error is None:
        print(
            f"  PASS final_status={summary.get('final_status', '')} "
            f"indexed={integer_summary(summary.get('new')) + integer_summary(summary.get('modified'))} "
            f"job={ingestion_job_id}"
        )
    else:
        failures += len(staged_documents)
        print(f"  FAIL {batch_error}", file=sys.stderr)

    print(
        f"Done. processed={processed} staged={len(staged_documents)} failures={failures} "
        f"report={display_path(report_path)}"
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
