"""Download real public reference files (CMS) and build compact reference tables.

Outputs (data/reference/, gitignored because CPT codes are AMA-copyrighted):
  icd10cm.csv   code, billable, short_desc       (CMS ICD-10-CM FY2027 order file)
  ncci_ptp.csv  col1, col2, modifier_indicator, rationale  (active Medicaid NCCI practitioner
                PTP edits, effective 2026-10-01, restricted to the simulator's code catalogue)
  mue.csv       code, mue_value, mai             (Medicare NCCI practitioner MUE table, Q4 2026)
"""
from __future__ import annotations

import hashlib
import io
import urllib.request
import zipfile

import pandas as pd

from src.common import DOWNLOADS, REFERENCE, catalog, ensure_dirs

CMS = "https://www.cms.gov/files/zip/"
FILES = {
    "icd": "2027-code-descriptions-tabular-order.zip",
    "ptp": "medicaid-ncci-2026-q4-ptp-edits-practitioner-services.zip",
    "mue": "medicare-ncci-2026-q4-practitioner-services-mue-table.zip",
}


def _download(name: str) -> bytes:
    path = DOWNLOADS / name
    if not path.exists():
        req = urllib.request.Request(CMS + name, headers={"User-Agent": "Mozilla/5.0 (portfolio project)"})
        with urllib.request.urlopen(req, timeout=300) as r:
            path.write_bytes(r.read())
    return path.read_bytes()


def sha256(name: str) -> str:
    return hashlib.sha256((DOWNLOADS / name).read_bytes()).hexdigest()


def catalog_codes() -> set[str]:
    return set(catalog()["codes"].keys())


def build_icd() -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(_download(FILES["icd"])))
    member = next(n for n in z.namelist() if n.endswith("icd10cm_order_2027.txt"))
    rows = []
    for line in z.read(member).decode("latin-1").splitlines():
        if len(line) < 16:
            continue
        rows.append((line[6:13].strip(), int(line[14]), line[16:76].strip()))
    df = pd.DataFrame(rows, columns=["code", "billable", "short_desc"])
    df.to_csv(REFERENCE / "icd10cm.csv", index=False)
    return df


def build_ptp() -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(_download(FILES["ptp"])))
    member = next(n for n in z.namelist() if n.endswith(".txt"))
    codes = catalog_codes()
    keep = []
    with z.open(member) as f:
        for raw in io.TextIOWrapper(f, encoding="latin-1"):
            parts = raw.rstrip("\r\n").split("\t")
            if len(parts) < 6 or parts[0] not in codes or parts[1] not in codes:
                continue
            if parts[3].strip():          # deletion date set -> edit no longer active
                continue
            keep.append((parts[0], parts[1], int(parts[4]), parts[5].strip()))
    df = pd.DataFrame(keep, columns=["col1", "col2", "modifier_indicator", "rationale"])
    df.to_csv(REFERENCE / "ncci_ptp.csv", index=False)
    return df


def build_mue() -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(_download(FILES["mue"])))
    member = next(n for n in z.namelist() if n.endswith(".csv"))
    df = pd.read_csv(z.open(member), skiprows=1, encoding="latin-1", dtype=str)
    df.columns = ["code", "mue_value", "mai", "rationale"]
    df = df[df["code"].isin(catalog_codes())].copy()
    df["mue_value"] = df["mue_value"].astype(int)
    df["mai"] = df["mai"].str[0].astype(int)
    df[["code", "mue_value", "mai"]].to_csv(REFERENCE / "mue.csv", index=False)
    return df[["code", "mue_value", "mai"]]


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(REFERENCE / f"{name}.csv", dtype={"code": str, "col1": str, "col2": str})


def main() -> None:
    ensure_dirs()
    icd, ptp, mue = build_icd(), build_ptp(), build_mue()
    print(f"ICD-10-CM codes: {len(icd):,}  |  active PTP pairs in catalogue: {len(ptp)}  |  MUE rows: {len(mue)}")
    for k, v in FILES.items():
        print(f"  {k}: {v}  sha256={sha256(v)[:16]}...")


if __name__ == "__main__":
    main()
