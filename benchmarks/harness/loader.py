"""Load and validate a versioned golden dataset from disk."""

import json
from pathlib import Path

from pydantic import ValidationError

from benchmarks.harness.models import (
    BenchmarkCase,
    BenchmarkDataset,
    CompanySeedSpec,
    DatasetManifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATASETS_ROOT = REPOSITORY_ROOT / "benchmarks" / "datasets"


class DatasetError(RuntimeError):
    """The dataset on disk is inconsistent and must not be benchmarked."""


def dataset_directory(name: str = "extraction", version: str = "v1") -> Path:
    return DATASETS_ROOT / name / version


def load_dataset(name: str = "extraction", version: str = "v1") -> BenchmarkDataset:
    directory = dataset_directory(name, version)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise DatasetError(f"dataset manifest does not exist: {manifest_path}")
    manifest = _parse_manifest(manifest_path)
    if manifest.dataset != name or manifest.version != version:
        raise DatasetError("manifest identity does not match the dataset directory")

    case_paths = sorted((directory / "cases").glob("*.json"))
    cases = tuple(_parse_case(path) for path in case_paths)
    if len(cases) != manifest.case_count:
        raise DatasetError(
            f"manifest declares {manifest.case_count} cases but {len(cases)} case files exist"
        )
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise DatasetError("case_id values must be unique across the dataset")
    for path, case in zip(case_paths, cases, strict=True):
        if path.stem != case.case_id:
            raise DatasetError(f"case file name {path.name} must match its case_id")

    companies = _parse_companies(directory / "companies.json")
    company_names = [spec.canonical_name for spec in companies]
    if len(company_names) != len(set(company_names)):
        raise DatasetError("company canonical names must be unique")
    return BenchmarkDataset(manifest=manifest, cases=cases, companies=companies)


def _parse_manifest(path: Path) -> DatasetManifest:
    try:
        return DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise DatasetError(f"invalid dataset manifest {path.name}: {exc}") from exc


def _parse_case(path: Path) -> BenchmarkCase:
    try:
        return BenchmarkCase.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise DatasetError(f"invalid benchmark case {path.name}: {exc}") from exc


def _parse_companies(path: Path) -> tuple[CompanySeedSpec, ...]:
    if not path.is_file():
        return ()
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetError(f"invalid companies.json: {exc}") from exc
    if not isinstance(entries, list):
        raise DatasetError("companies.json must contain a JSON array")
    try:
        return tuple(CompanySeedSpec.model_validate(entry) for entry in entries)
    except ValidationError as exc:
        raise DatasetError(f"invalid company seed entry: {exc}") from exc
