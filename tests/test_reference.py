"""The code catalogue must agree with the real CMS reference files."""
from src import reference
from src.common import catalog


def test_every_cpt_code_has_a_cms_mue_row():
    mue = set(reference.load("mue")["code"])
    missing = set(catalog()["codes"]) - mue
    assert not missing, f"catalogue codes absent from the CMS MUE table: {missing}"


def test_catalogue_diagnoses_are_billable_icd10cm():
    icd = reference.load("icd10cm")
    billable = set(icd.loc[icd.billable == 1, "code"])
    cat = catalog()
    used = {dx for pool in cat["dx_pools"].values() for dx in pool}
    used |= {dx for g in cat["support"].values() for k in ("strong", "weak") for dx in g.get(k, [])}
    assert used <= billable, used - billable


def test_invalid_dx_headers_are_real_but_not_billable():
    icd = reference.load("icd10cm").set_index("code")["billable"]
    for c in catalog()["invalid_dx_headers"]:
        assert c in icd.index and icd[c] == 0


def test_planted_code_pair_is_a_real_active_ncci_edit():
    ptp = reference.load("ncci_ptp")
    row = ptp[(ptp.col1 == "43239") & (ptp.col2 == "43235")]
    assert len(row) == 1 and int(row.modifier_indicator.iloc[0]) == 0
