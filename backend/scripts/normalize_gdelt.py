import csv
import json
import sys
from pathlib import Path

# CAMEO code → your 7 event types
CAMEO_MAP = {
    "10": "Diplomatic",        "11": "Trade Policy",
    "12": "Trade Policy",      "13": "Sanctions",
    "14": "Sanctions",         "15": "Elections",
    "16": "Elections",         "17": "Conflict",
    "18": "Conflict",          "19": "Conflict",
    "20": "Regulation",        "21": "Economic Data",
    "08": "Trade Policy",      "09": "Sanctions",
}

def map_event_type(cameo_code: str) -> str:
    prefix = cameo_code[:2]
    return CAMEO_MAP.get(prefix, "Economic Data")

def map_sentiment(avg_tone: float, goldstein: float) -> str:
    # Combine tone and goldstein for better signal
    score = (avg_tone + goldstein) / 2
    if score > 1.0:
        return "positive"
    elif score < -1.0:
        return "negative"
    return "neutral"

def normalize_gdelt(input_path: str, output_path: str):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    written = 0
    skipped = 0

    with open(input_path, "r", encoding="utf-8", errors="ignore") as infile, \
         open(output_path, "w", encoding="utf-8") as outfile:

        reader = csv.reader(infile, delimiter="\t")

        for row in reader:
            # Skip rows that are too short
            if len(row) < 58:
                skipped += 1
                continue

            try:
                event_id    = row[0].strip()
                date_raw    = row[1].strip()          # YYYYMMDD
                actor1      = row[6].strip()
                country1    = row[7].strip()
                actor2      = row[16].strip()
                country2    = row[17].strip()
                cameo_code  = row[26].strip()
                goldstein   = float(row[28]) if row[28] else 0.0
                num_articles= int(row[30])   if row[30] else 0
                avg_tone    = float(row[34]) if row[34] else 0.0
                source_url  = row[57].strip()

                # Skip low-signal rows
                if num_articles < 2:
                    skipped += 1
                    continue

                if not cameo_code or not actor1:
                    skipped += 1
                    continue

                # Format date as ISO
                if len(date_raw) == 8:
                    iso_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
                else:
                    skipped += 1
                    continue

                record = {
                    "event_id":     event_id,
                    "published_at": iso_date,
                    "actor1":       actor1,
                    "actor2":       actor2,
                    "country":      country1 or country2,
                    "event_type":   map_event_type(cameo_code),
                    "cameo_code":   cameo_code,
                    "sentiment":    map_sentiment(avg_tone, goldstein),
                    "goldstein":    goldstein,
                    "avg_tone":     avg_tone,
                    "num_articles": num_articles,
                    "source_url":   source_url,
                    # Label for trpython scripts\normalize_gdelt.py data\raw\gdelt_combined.csv data\processed\gdelt.normalized.jsonlaining (1 = relevant geopolitical event)
                    "label":        1,
                }

                outfile.write(json.dumps(record) + "\n")
                written += 1

            except (ValueError, IndexError):
                skipped += 1
                continue

    print(f"Done. Written: {written:,}  |  Skipped: {skipped:,}")
    print(f"Output: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python normalize_gdelt.py <input.csv> <output.jsonl>")
        sys.exit(1)
    normalize_gdelt(sys.argv[1], sys.argv[2])