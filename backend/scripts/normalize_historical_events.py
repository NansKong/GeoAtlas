from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


BACKEND_ROOT = Path(__file__).resolve().parents[1]
XML_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

GDELT_ROOT_EVENT_MAP = {
    "01": "Diplomatic",
    "02": "Diplomatic",
    "03": "Diplomatic",
    "04": "Diplomatic",
    "05": "Diplomatic",
    "06": "Diplomatic",
    "07": "Diplomatic",
    "08": "Trade Policy",
    "09": "Sanctions",
    "10": "Diplomatic",
    "11": "Trade Policy",
    "12": "Trade Policy",
    "13": "Sanctions",
    "14": "Sanctions",
    "15": "Elections",
    "16": "Elections",
    "17": "Conflict",
    "18": "Conflict",
    "19": "Conflict",
    "20": "Regulation",
}

ACLED_EVENT_MAP = {
    "battles": "Conflict",
    "explosions/remote violence": "Conflict",
    "violence against civilians": "Conflict",
    "riots": "Conflict",
    "protests": "Conflict",
    "strategic developments": "Regulation",
}

GDELT_COLUMNS = [
    "GLOBALEVENTID",
    "SQLDATE",
    "MonthYear",
    "Year",
    "FractionDate",
    "Actor1Code",
    "Actor1Name",
    "Actor1CountryCode",
    "Actor1KnownGroupCode",
    "Actor1EthnicCode",
    "Actor1Religion1Code",
    "Actor1Religion2Code",
    "Actor1Type1Code",
    "Actor1Type2Code",
    "Actor1Type3Code",
    "Actor2Code",
    "Actor2Name",
    "Actor2CountryCode",
    "Actor2KnownGroupCode",
    "Actor2EthnicCode",
    "Actor2Religion1Code",
    "Actor2Religion2Code",
    "Actor2Type1Code",
    "Actor2Type2Code",
    "Actor2Type3Code",
    "IsRootEvent",
    "EventCode",
    "EventBaseCode",
    "EventRootCode",
    "QuadClass",
    "GoldsteinScale",
    "NumMentions",
    "NumSources",
    "NumArticles",
    "AvgTone",
    "Actor1Geo_Type",
    "Actor1Geo_FullName",
    "Actor1Geo_CountryCode",
    "Actor1Geo_ADM1Code",
    "Actor1Geo_Lat",
    "Actor1Geo_Long",
    "Actor1Geo_FeatureID",
    "Actor2Geo_Type",
    "Actor2Geo_FullName",
    "Actor2Geo_CountryCode",
    "Actor2Geo_ADM1Code",
    "Actor2Geo_Lat",
    "Actor2Geo_Long",
    "Actor2Geo_FeatureID",
    "ActionGeo_Type",
    "ActionGeo_FullName",
    "ActionGeo_CountryCode",
    "ActionGeo_ADM1Code",
    "ActionGeo_Lat",
    "ActionGeo_Long",
    "ActionGeo_FeatureID",
    "DATEADDED",
    "SOURCEURL",
]


def _resolve_path(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    path = Path(path_str)
    if path.is_absolute():
        return path
    return BACKEND_ROOT / path


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_int(value: object) -> int | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_float(value: object) -> float | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _date_from_yyyymmdd(raw: object) -> str | None:
    text = _clean(raw)
    if not re.fullmatch(r"\d{8}", text):
        return None
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _parse_date(raw: object) -> str | None:
    text = _clean(raw)
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        return _date_from_yyyymmdd(text)
    numeric = _to_float(text)
    if numeric and numeric > 20000:
        parsed = datetime(1899, 12, 30) + timedelta(days=numeric)
        return parsed.date().isoformat()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _published_at_iso(event_date: str | None) -> str | None:
    if not event_date:
        return None
    return f"{event_date}T00:00:00Z"


def _canonical_id(*parts: object) -> str:
    normalized = "|".join(_clean(part).lower() for part in parts if _clean(part))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.netloc.lower() or None


def _sentiment_label(score: float | None) -> str | None:
    if score is None:
        return None
    if score <= -1.0:
        return "negative"
    if score >= 1.0:
        return "positive"
    return "neutral"


def _is_reuters_marker(text: str) -> bool:
    lowered = text.lower()
    return "reuters" in lowered or "/ultime-notizie-reuters/" in lowered


def _is_reuters_row(row: dict[str, object]) -> bool:
    source_url = _clean(row.get("SOURCEURL"))
    actor_fields = " ".join(
        _clean(row.get(key))
        for key in ("Actor1Code", "Actor1Name", "Actor2Code", "Actor2Name")
    )
    return _is_reuters_marker(source_url) or _is_reuters_marker(actor_fields)


def _gdelt_taxonomy(event_root_code: str, event_code: str) -> str:
    root = _clean(event_root_code).zfill(2)[:2]
    code_prefix = _clean(event_code).zfill(2)[:2]
    return GDELT_ROOT_EVENT_MAP.get(root) or GDELT_ROOT_EVENT_MAP.get(code_prefix) or "Economic Data"


def _build_gdelt_title(actor1: str, actor2: str, event_type: str, location: str) -> str:
    if actor1 and actor2:
        return f"{actor1} / {actor2} - {event_type}"
    if actor1:
        return f"{actor1} - {event_type}"
    if actor2:
        return f"{actor2} - {event_type}"
    if location:
        return f"{event_type} - {location}"
    return event_type


def _build_gdelt_description(row: dict[str, object], event_type: str) -> str:
    actor1 = _clean(row.get("Actor1Name"))
    actor2 = _clean(row.get("Actor2Name"))
    location = _clean(row.get("ActionGeo_FullName"))
    mentions = _to_int(row.get("NumMentions"))
    articles = _to_int(row.get("NumArticles"))
    pieces = [piece for piece in [actor1, actor2, location] if piece]
    prefix = " / ".join(pieces) if pieces else "GDELT event"
    counts = []
    if mentions is not None:
        counts.append(f"{mentions} mentions")
    if articles is not None:
        counts.append(f"{articles} articles")
    suffix = f" ({', '.join(counts)})" if counts else ""
    return f"{prefix} mapped to {event_type}{suffix}"


def _normalize_gdelt_row(row: dict[str, object], provider: str) -> dict | None:
    event_date = _date_from_yyyymmdd(row.get("SQLDATE"))
    event_code = _clean(row.get("EventCode"))
    event_root_code = _clean(row.get("EventRootCode"))
    actor1 = _clean(row.get("Actor1Name"))
    actor2 = _clean(row.get("Actor2Name"))
    country = _clean(row.get("ActionGeo_CountryCode")) or _clean(row.get("Actor1CountryCode")) or _clean(row.get("Actor2CountryCode"))
    location = _clean(row.get("ActionGeo_FullName")) or _clean(row.get("Actor1Geo_FullName")) or _clean(row.get("Actor2Geo_FullName"))
    source_url = _clean(row.get("SOURCEURL")) or None
    num_articles = _to_int(row.get("NumArticles"))
    num_mentions = _to_int(row.get("NumMentions"))
    num_sources = _to_int(row.get("NumSources"))
    goldstein = _to_float(row.get("GoldsteinScale"))
    avg_tone = _to_float(row.get("AvgTone"))
    if not event_date or not event_code:
        return None

    taxonomy_event_type = _gdelt_taxonomy(event_root_code, event_code)
    source_name = "Reuters" if provider == "reuters" else (_host_from_url(source_url) or "GDELT")
    sentiment_score = None
    if goldstein is not None and avg_tone is not None:
        sentiment_score = round((goldstein + avg_tone) / 2.0, 4)
    elif avg_tone is not None:
        sentiment_score = avg_tone
    elif goldstein is not None:
        sentiment_score = goldstein

    canonical_id = _canonical_id(
        event_date,
        event_code,
        source_url,
        actor1,
        actor2,
        country,
        location,
    )
    return {
        "canonical_id": canonical_id,
        "provider": provider,
        "provider_record_id": _clean(row.get("GLOBALEVENTID")) or canonical_id,
        "published_at": _published_at_iso(event_date),
        "event_date": event_date,
        "title": _build_gdelt_title(actor1, actor2, taxonomy_event_type, location),
        "description": _build_gdelt_description(row, taxonomy_event_type),
        "source_name": source_name,
        "source_url": source_url,
        "country": country or None,
        "region": None,
        "admin1": _clean(row.get("ActionGeo_ADM1Code")) or None,
        "location_name": location or None,
        "latitude": _to_float(row.get("ActionGeo_Lat")),
        "longitude": _to_float(row.get("ActionGeo_Long")),
        "event_type": taxonomy_event_type,
        "sub_event_type": event_code,
        "event_code": event_code,
        "event_root_code": event_root_code or None,
        "actor1": actor1 or None,
        "actor2": actor2 or None,
        "fatalities": None,
        "num_mentions": num_mentions,
        "num_sources": num_sources,
        "num_articles": num_articles,
        "sentiment_score": sentiment_score,
        "sentiment_label": _sentiment_label(sentiment_score),
        "relevance_label": 1,
        "metadata": {
            "raw_provider": "gdelt",
            "quad_class": _clean(row.get("QuadClass")) or None,
            "is_root_event": _clean(row.get("IsRootEvent")) or None,
            "goldstein_scale": goldstein,
            "avg_tone": avg_tone,
            "actor1_code": _clean(row.get("Actor1Code")) or None,
            "actor2_code": _clean(row.get("Actor2Code")) or None,
            "actor1_geo": _clean(row.get("Actor1Geo_FullName")) or None,
            "actor2_geo": _clean(row.get("Actor2Geo_FullName")) or None,
            "date_added": _date_from_yyyymmdd(row.get("DATEADDED")),
        },
    }


def _acled_taxonomy(event_type: str, sub_event_type: str, disorder_type: str) -> str:
    for value in (event_type, sub_event_type, disorder_type):
        lowered = _clean(value).lower()
        if lowered in ACLED_EVENT_MAP:
            return ACLED_EVENT_MAP[lowered]
    if "violence" in _clean(disorder_type).lower():
        return "Conflict"
    return "Conflict"


def _acled_sentiment(fatalities: int | None, disorder_type: str) -> tuple[float | None, str | None]:
    if fatalities and fatalities > 0:
        return float(-fatalities), "negative"
    if "violence" in disorder_type.lower():
        return -1.0, "negative"
    return 0.0, "neutral"


def _normalize_acled_row(row: dict[str, object], source_name: str) -> dict | None:
    event_date = _parse_date(row.get("WEEK") or row.get("event_date") or row.get("week"))
    country = _clean(row.get("COUNTRY") or row.get("country"))
    admin1 = _clean(row.get("ADMIN1") or row.get("admin1"))
    raw_event_type = _clean(row.get("EVENT_TYPE") or row.get("event_type"))
    sub_event_type = _clean(row.get("SUB_EVENT_TYPE") or row.get("sub_event_type"))
    disorder_type = _clean(row.get("DISORDER_TYPE") or row.get("disorder_type"))
    if not event_date or not country or not raw_event_type:
        return None

    events = _to_int(row.get("EVENTS") or row.get("events"))
    fatalities = _to_int(row.get("FATALITIES") or row.get("fatalities"))
    latitude = _to_float(row.get("CENTROID_LATITUDE") or row.get("latitude"))
    longitude = _to_float(row.get("CENTROID_LONGITUDE") or row.get("longitude"))
    taxonomy_event_type = _acled_taxonomy(raw_event_type, sub_event_type, disorder_type)
    sentiment_score, sentiment_label = _acled_sentiment(fatalities, disorder_type)
    record_id = _clean(row.get("ID") or row.get("id")) or None
    title_bits = [piece for piece in [sub_event_type or raw_event_type, admin1, country] if piece]
    title = " - ".join(title_bits)
    description = f"ACLED weekly aggregate with {events or 0} event(s)"
    if fatalities is not None:
        description += f" and {fatalities} fatalities"

    canonical_id = _canonical_id(
        event_date,
        country,
        admin1,
        raw_event_type,
        sub_event_type,
        source_name,
    )
    return {
        "canonical_id": canonical_id,
        "provider": "acled",
        "provider_record_id": record_id or canonical_id,
        "published_at": _published_at_iso(event_date),
        "event_date": event_date,
        "title": title,
        "description": description,
        "source_name": "ACLED",
        "source_url": None,
        "country": country,
        "region": _clean(row.get("REGION") or row.get("region")) or None,
        "admin1": admin1 or None,
        "location_name": admin1 or country,
        "latitude": latitude,
        "longitude": longitude,
        "event_type": taxonomy_event_type,
        "sub_event_type": sub_event_type or raw_event_type,
        "event_code": None,
        "event_root_code": None,
        "actor1": None,
        "actor2": None,
        "fatalities": fatalities,
        "num_mentions": None,
        "num_sources": None,
        "num_articles": events,
        "sentiment_score": sentiment_score,
        "sentiment_label": sentiment_label,
        "relevance_label": 1,
        "metadata": {
            "raw_provider": "acled",
            "source_file": source_name,
            "raw_event_type": raw_event_type,
            "disorder_type": disorder_type or None,
            "population_exposure": _clean(row.get("POPULATION_EXPOSURE") or row.get("population_exposure")) or None,
        },
    }


def _iter_json_rows(path: Path) -> Iterator[dict[str, object]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)
        return
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for row in payload:
                if isinstance(row, dict):
                    yield row
        elif isinstance(payload, dict):
            yield payload
        return
    raise ValueError(f"Unsupported JSON input: {path}")


def _iter_dict_csv_rows(path: Path) -> Iterator[dict[str, object]]:
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        reader = csv.DictReader(handle, dialect=dialect)
        for row in reader:
            yield dict(row)


def _iter_gdelt_raw_rows(path: Path) -> Iterator[dict[str, object]]:
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if len(row) < len(GDELT_COLUMNS):
                continue
            yield dict(zip(GDELT_COLUMNS, row[: len(GDELT_COLUMNS)]))


def _iter_gdelt_rows(input_path: Path) -> Iterator[dict[str, object]]:
    paths = [input_path] if input_path.is_file() else sorted(input_path.rglob("*.CSV")) + sorted(input_path.rglob("*.csv"))
    for path in paths:
        suffix = path.suffix.lower()
        if suffix in {".json", ".jsonl"}:
            yield from _iter_json_rows(path)
        else:
            yield from _iter_gdelt_raw_rows(path)


def _excel_col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - 64)
    return index - 1


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("a:v", XML_NS)
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iterfind(".//a:t", XML_NS))
    if value_node is None:
        return ""
    value = value_node.text or ""
    if cell_type == "s":
        return shared_strings[int(value)]
    return value


def _load_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(node.text or "" for node in item.iterfind(".//a:t", XML_NS))
        for item in root.findall("a:si", XML_NS)
    ]


def _iter_xlsx_rows(path: Path) -> Iterator[dict[str, object]]:
    with zipfile.ZipFile(path) as workbook:
        shared_strings = _load_shared_strings(workbook)
        with workbook.open("xl/worksheets/sheet1.xml") as handle:
            row_iter = ET.iterparse(handle, events=("end",))
            headers: list[str] | None = None
            for _, elem in row_iter:
                if not elem.tag.endswith("row"):
                    continue
                values: dict[int, str] = {}
                for cell in elem.findall("a:c", XML_NS):
                    ref = cell.attrib.get("r", "")
                    values[_excel_col_index(ref)] = _xlsx_cell_value(cell, shared_strings)
                if values:
                    width = max(values) + 1
                    dense_row = [values.get(idx, "") for idx in range(width)]
                    if headers is None:
                        headers = [header.strip() for header in dense_row]
                    else:
                        padded = dense_row + [""] * max(0, len(headers) - len(dense_row))
                        yield {headers[idx]: padded[idx] for idx in range(len(headers))}
                elem.clear()


def _iter_acled_rows(input_path: Path) -> Iterator[tuple[dict[str, object], str]]:
    if input_path.is_file():
        paths = [input_path]
    else:
        paths = sorted(input_path.rglob("*.xlsx")) + sorted(input_path.rglob("*.csv")) + sorted(input_path.rglob("*.jsonl")) + sorted(input_path.rglob("*.json"))

    for path in paths:
        suffix = path.suffix.lower()
        if suffix == ".xlsx":
            iterator: Iterable[dict[str, object]] = _iter_xlsx_rows(path)
        elif suffix in {".json", ".jsonl"}:
            iterator = _iter_json_rows(path)
        else:
            iterator = _iter_dict_csv_rows(path)
        for row in iterator:
            yield row, path.name


def normalize_provider(provider: str, input_path: Path, output_path: Path, max_records: int | None = None) -> dict[str, int]:
    provider = provider.lower()
    written = 0
    skipped = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        if provider in {"gdelt", "reuters"}:
            for row in _iter_gdelt_rows(input_path):
                if provider == "reuters" and not _is_reuters_row(row):
                    skipped += 1
                    continue
                if provider == "gdelt" and not row.get("EventCode"):
                    skipped += 1
                    continue
                normalized = _normalize_gdelt_row(row, provider)
                if not normalized:
                    skipped += 1
                    continue
                handle.write(json.dumps(normalized, ensure_ascii=True) + "\n")
                written += 1
                if max_records and written >= max_records:
                    break
        elif provider == "acled":
            for row, source_name in _iter_acled_rows(input_path):
                normalized = _normalize_acled_row(row, source_name)
                if not normalized:
                    skipped += 1
                    continue
                handle.write(json.dumps(normalized, ensure_ascii=True) + "\n")
                written += 1
                if max_records and written >= max_records:
                    break
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    return {"written": written, "skipped": skipped}


def combine_datasets(
    output_path: Path,
    gdelt_input: Path | None,
    acled_input: Path | None,
    reuters_input: Path | None,
    max_records_per_provider: int | None = None,
) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {
        "reuters": {"written": 0, "skipped": 0},
        "acled": {"written": 0, "skipped": 0},
        "gdelt": {"written": 0, "skipped": 0},
        "duplicates_skipped": 0,
    }
    priority_ids: set[str] = set()

    def _write_records(provider: str, input_path: Path | None, handle) -> None:
        if input_path is None or not input_path.exists():
            return
        written = 0
        if provider in {"gdelt", "reuters"}:
            for row in _iter_gdelt_rows(input_path):
                if provider == "reuters" and not _is_reuters_row(row):
                    counts[provider]["skipped"] += 1
                    continue
                normalized = _normalize_gdelt_row(row, provider)
                if not normalized:
                    counts[provider]["skipped"] += 1
                    continue
                if provider == "gdelt" and normalized["canonical_id"] in priority_ids:
                    counts["duplicates_skipped"] += 1
                    continue
                if provider == "reuters":
                    priority_ids.add(normalized["canonical_id"])
                handle.write(json.dumps(normalized, ensure_ascii=True) + "\n")
                counts[provider]["written"] += 1
                written += 1
                if max_records_per_provider and written >= max_records_per_provider:
                    break
            return

        for row, source_name in _iter_acled_rows(input_path):
            normalized = _normalize_acled_row(row, source_name)
            if not normalized:
                counts[provider]["skipped"] += 1
                continue
            handle.write(json.dumps(normalized, ensure_ascii=True) + "\n")
            counts[provider]["written"] += 1
            written += 1
            if max_records_per_provider and written >= max_records_per_provider:
                break

    with output_path.open("w", encoding="utf-8") as handle:
        _write_records("reuters", reuters_input, handle)
        _write_records("acled", acled_input, handle)
        _write_records("gdelt", gdelt_input, handle)

    return counts


def parse_args() -> argparse.Namespace:
    argv = sys.argv[1:]
    if argv and argv[0] in {"gdelt", "acled", "reuters"}:
        argv = ["normalize", *argv]

    parser = argparse.ArgumentParser(description="Normalize GDELT, ACLED, and Reuters-derived historical datasets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize_parser = subparsers.add_parser("normalize")
    normalize_parser.add_argument("provider", choices=["gdelt", "acled", "reuters"])
    normalize_parser.add_argument("input")
    normalize_parser.add_argument("output")
    normalize_parser.add_argument("--max-records", type=int, default=None)

    combine_parser = subparsers.add_parser("combine")
    combine_parser.add_argument("output")
    combine_parser.add_argument("--gdelt-input", default="data/raw/gdelt")
    combine_parser.add_argument("--acled-input", default="data/ACLED")
    combine_parser.add_argument("--reuters-input", default="data/raw/gdelt")
    combine_parser.add_argument("--max-records-per-provider", type=int, default=None)

    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    if args.command == "normalize":
        input_path = _resolve_path(args.input)
        output_path = _resolve_path(args.output)
        if input_path is None or not input_path.exists():
            raise SystemExit(f"Input path not found: {args.input}")
        if output_path is None:
            raise SystemExit(f"Output path is invalid: {args.output}")
        stats = normalize_provider(args.provider, input_path, output_path, max_records=args.max_records)
        print(json.dumps({"provider": args.provider, "output": str(output_path), **stats}, ensure_ascii=True))
        return

    output_path = _resolve_path(args.output)
    if output_path is None:
        raise SystemExit(f"Output path is invalid: {args.output}")
    gdelt_input = _resolve_path(args.gdelt_input)
    acled_input = _resolve_path(args.acled_input)
    reuters_input = _resolve_path(args.reuters_input)
    stats = combine_datasets(
        output_path=output_path,
        gdelt_input=gdelt_input,
        acled_input=acled_input,
        reuters_input=reuters_input,
        max_records_per_provider=args.max_records_per_provider,
    )
    print(json.dumps({"provider": "combined", "output": str(output_path), **stats}, ensure_ascii=True))


if __name__ == "__main__":
    main()
