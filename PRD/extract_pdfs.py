import os
import sys

# Install pypdf2 if not already installed
os.system("pip install pypdf2 -q")

import PyPDF2

pdfs = [
    r"D:\GeoAtlas\PRODUCT REQUIREMENTS DOCUMENT.pdf",
    r"D:\GeoAtlas\Architecture.pdf",
    r"D:\GeoAtlas\Database Architecture.pdf",
    r"D:\GeoAtlas\news ingestions.pdf",
    r"D:\GeoAtlas\GeoAtlas_Production_Improvement_Report.pdf",
]

output_file = r"D:\GeoAtlas\extracted_text.txt"

with open(output_file, "w", encoding="utf-8") as out:
    for path in pdfs:
        print(f"Processing: {path}")
        out.write(f"\n\n{'='*60}\n{path}\n{'='*60}\n\n")
        try:
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for i, page in enumerate(reader.pages):
                    text = page.extract_text()
                    if text:
                        out.write(f"--- Page {i+1} ---\n{text}\n")
        except Exception as e:
            out.write(f"ERROR reading file: {e}\n")
            print(f"  ERROR: {e}")

print(f"\nDone! Output saved to: {output_file}")
