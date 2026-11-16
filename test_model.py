"""Regression and consistency tests of the model outputs (run by run_all.sh after the models, before the figures).

Each test raises AssertionError with a message; `python test_model.py` prints a summary and exits non-zero on failure.
"""
import json
import sys

import inputs as I
import optimise as O

OUT = O.OUT
L = lambda f: json.load(open(OUT / f))
TOL = 1e-6


def close(a, b, rel=1e-6, abs_=1e-6):
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def test_demand_conservation(S):
    """Every segment's end uses (plus catenary) sum to its 2025 demand."""
    D = S["demand_twh"]
    by_seg = {}
    for k, t in S["end_use_twh"].items():
        by_seg[k.split("|")[0]] = by_seg.get(k.split("|")[0], 0.0) + t
    by_seg["hdv"] += sum(S["ers_twh"].values())
    for s in D:
        assert abs(by_seg[s] - D[s]) < 1e-5 * D[s], f"demand not conserved in {s}: {by_seg[s]} vs {D[s]}"


def test_no_shortfall(S):
    """No unserved liquid fuel in the central case."""
    assert S["shortfall_total_twh"] < TOL, f"unserved fuel in the central case: {S['shortfall_total_twh']} TWh"


def test_fuel_balances(S):
    """Supply of drop-in, jet, ethanol, methane, methanol and ammonia covers carrier demand."""
    c = S["carrier_twh"]
    f = S["fuels_twh"]
    hc = sum(f[k] for k in ("kelp_hc", "straw_ft", "cane_htl", "forest_htl", "hefa", "canola_hvo", "efuel_ft_solar",
                            "efuel_ft_wind"))
    assert hc + f["alcohol_to_jet"] >= c.get("dropin", 0) + c.get("jet", 0) - 1e-5, "drop-in plus jet not supplied"
    assert f["ethanol"] >= c.get("ethanol", 0) + f["alcohol_to_jet"] / 0.925 - 1e-5, "ethanol balance"
    assert f["waste_biomethane"] + f["kelp_methane"] >= c.get("methane", 0) + 1.5 * f["bio_methanol"] - 1e-5, "methane balance"
    assert f["e_methanol"] + f["bio_methanol"] >= c.get("methanol", 0) - 1e-5, "methanol balance"
    assert f["e_ammonia"] >= c.get("ammonia", 0) - 1e-5, "ammonia balance"


def test_electricity_balance(S):
    """Generation covers all electricity uses plus at most the network losses."""
    g = S["generation_total_twh"]
    use = sum(S["electricity_twh"].values())
    assert g >= use * 1.0 - 1e-4, f"generation {g} below use {use}"
    assert g <= use * 1.06 + 1e-4, f"generation {g} exceeds use plus losses {use * 1.05}"


def test_heat_balance(S):
    """Each regional heat pool is fully supplied."""
    for pl, h in S["heat_by_pool"].items():
        supply = h["hp"] + h["tes"] + h["eb"] + h["smr"]
        assert supply >= h["demand"] - 1e-5, f"heat pool {pl} short"


def test_catenary_accounting(S):
    """Built km equal the sum of built corridors; no traffic on unbuilt ones; decisions binary."""
    km = sum(S["ers_corridors"][c]["km"] for c, b in S["ers_built"].items() if b)
    assert abs(km - S["ers_km_electrified"]) < 1e-6, "catenary km must be the sum of built corridors"
    for c, t in S["ers_twh"].items():
        cap = S["ers_corridors"][c]["twh_diesel"]
        assert t <= cap * S["ers_built"][c] + 1e-6, f"traffic on unbuilt corridor {c}"
        assert S["ers_built"][c] in (0, 1), "corridor decision must be binary"


def test_kelp_and_n(S):
    """Kelp areas within zone bounds; nitrogen supply (natural, fish farms, depth cycling) closes."""
    for z, a in S["kelp_km2"].items():
        assert a <= S["kelp_zone_table"][z]["area_km2"] + 1e-6, f"kelp area above bound in {z}"
    n = S["kelp_n_supply_kt"]
    assert abs(sum(n.values()) - S["kelp_n_kt"]) < 1e-6, "kelp nitrogen supply must close"
    assert n["depth_cycling"] >= -1e-9, "negative depth-cycling nitrogen"


def test_emissions(S):
    """Life-cycle parts sum to the total, the range brackets it, and the fossil baseline recomputes."""
    tot, parts = O.residual_emissions(S, breakdown=True)
    assert abs(tot - S["residual_wtw_mt"]) < 1e-9 and abs(sum(parts.values()) - tot) < 1e-9, "LCA sum"
    assert S["residual_range_mt"]["lo"] <= tot <= S["residual_range_mt"]["hi"], "LCA range brackets the central value"
    fossil = sum(I.co2_t_per_mwh(s) * d for s, d in S["demand_twh"].items())
    assert abs(fossil - S["fossil_wtw_mt"]) < 1e-6, "fossil baseline"


def test_costs(S):
    """Objective within range; fossil benchmarks ordered."""
    assert 0 < S["objective_bn"] < 500, "objective out of range"
    assert S["fossil_cost_bn"]["avg2025"] < S["fossil_cost_bn"]["oct2026"], "fossil benchmarks ordered"


def test_observed_data(S):
    """Observed inputs: complete hourly capacity factors, ISP calibration hit, APS volumes and EIA Brent used as read."""
    import numpy as np
    cf = np.load(O.HERE / "observed_data" / "cf_hourly.npz") if hasattr(O, "HERE") else np.load(OUT.parent / "observed_data" / "cf_hourly.npz")
    assert cf["wind"].shape == cf["pv"].shape == (24, 87672), "capacity factor arrays incomplete"
    assert np.isfinite(cf["wind"].astype(float)).all() and np.isfinite(cf["pv"].astype(float)).all(), "non-finite CF"
    sites = json.load(open(OUT.parent / "observed_data" / "sites.json"))["sites"]
    for n, m in sites.items():
        if m["isp_wind_cf"]:
            assert abs(m["wind_cf"] - m["isp_wind_cf"]) < 0.002, f"wind calibration {n}"
        if m["isp_pv_cf"]:
            assert abs(m["pv_cf"] - m["isp_pv_cf"]) < 0.002, f"PV calibration {n}"
    aps = json.load(open(OUT.parent / "observed_data" / "aps_2025.json"))
    assert aps["months"] == 12, "APS 2025 incomplete"
    assert abs(I.VOL_GL["diesel"] * 1000 - aps["sales_ml"]["Diesel oil: total (ML)"]) < 1e-6, "diesel volume not APS"
    px = json.load(open(OUT.parent / "observed_data" / "prices.json"))
    assert I.BRENT_USD_BBL["oct2026"] == px["brent_oct2026"] and abs(px["brent_oct2026"] - 123.93) < 0.01, "Brent anchor"


def test_hourly_reliability(S):
    """Hourly model: after the turbine top-up no year 2015-2024 leaves more than 0.002% of direct demand unserved."""
    D = L("dispatch.json")
    worst = D["robust"]["unserved_mwh_max"]
    assert worst <= 2e-5 * D["design"]["direct_twh"] * 1e6, f"unserved {worst} MWh"
    for n, v in D["design"]["systems"].items():
        assert v["battery_gw"] >= -1e-6 and v["battery_gwh"] >= -1e-6 and v["h2_store_gwh_el"] >= -1e-6, n


def test_calibration(S):
    """The annual model charges what the hourly model finds (within AUD 1/MWh)."""
    c = json.load(open(O.CALIBRATION))
    a = c["annual_prices_after"]
    h = c.get("hourly_last", c["hourly_pass1"])
    assert abs(a["direct"] - (h["direct"] + max(c["distribution_aud_mwh"], 0.0))) < 1.0, "direct calibration"
    assert abs(a["flex_with_electrolyser"] - (h["flex_with_electrolyser"] + O._base_params()["adder"]["net_flex"])) < 1.0, "flexible calibration"
    assert c["firming_multiplier"] >= 0, "negative firming"


def test_kelp_bounds(S):
    """Kelp never exceeds the ocean-data area or the deployment cap, in the central case and every Monte Carlo draw."""
    import kelp as K
    for z, a in S["kelp_km2"].items():
        assert a <= min(K.ZONES[z].area_km2, K.DEPLOYMENT_CAP_KM2) + 1e-6, z
    mc = L("montecarlo.json")
    lim = sum(min(z.area_km2, K.DEPLOYMENT_CAP_KM2) for z in K.ZONES.values())
    assert max(r["kelp_km2"] for r in mc["rows"]) <= lim + 1e-6, "Monte Carlo kelp above bounds"


def test_regional_balance(S):
    """Hourly design: no node has negative curtailment, inter-regional net exports sum to zero, and each node's energy
    balance closes (generation + turbines + battery output - curtailment - net export - loads = battery charging)."""
    D = L("dispatch.json")
    sysd = D["design"]["systems"]
    assert abs(sum(v["net_export_twh"] for v in sysd.values())) < 1e-3, "net exports"
    for n, v in sysd.items():
        assert v["curtail_twh"] >= -1e-3, f"negative curtailment {n}"
        assert close(v["wind_twh"] + v["pv_twh"], v["generation_twh"]), n
        charge = (v["wind_twh"] + v["pv_twh"] + v["turbine_twh"] + v["battery_twh_out"] - v["curtail_twh"]
                  - v["net_export_twh"] - v["direct_twh"] - v["flexible_twh"])
        assert v["battery_twh_out"] - 1e-3 <= charge <= v["battery_twh_out"] / 0.8 + 1e-3, f"balance {n}: {charge}"


def test_verification(S):
    """Final fleet, same capacities every year, nothing added, one-hour resolution over 2015-2024: expected (ten-year
    mean) unserved energy within the 0.002% reliability standard, no single year above 0.005%, non-negative curtailment
    and zero net inter-regional exports."""
    V = L("verify_hourly.json")
    assert V["step_h"] == 1 and len(V["years"]) == 10, "verification incomplete"
    u = [v["unserved_mwh"] for v in V["years"].values()]
    d = [v["direct_twh"] * 1e6 for v in V["years"].values()]
    assert sum(u) / len(u) <= 2e-5 * sum(d) / len(d), f"expected unserved {sum(u) / len(u):.0f} MWh"
    assert max(x / y for x, y in zip(u, d)) <= 5e-5, "a single year above 0.005% unserved"
    for y, v in V["years"].items():
        assert min(v["curtail_twh_by_node"].values()) >= -1e-3, y
        assert abs(sum(v["net_export_twh_by_node"].values())) < 1e-3, y


def test_reconciliation(S):
    """One portfolio: the annual model, given the hourly wind share, chooses a portfolio close to the hourly fleet, and
    the reconciled cost differs from the annual objective only by the electricity-supply terms it replaces."""
    R = L("reconciled.json")
    ph, pa = R["portfolio_hourly"], R["portfolio_annual"]
    assert abs(pa["wind_twh"] / (pa["wind_twh"] + pa["pv_twh"]) - ph["wind_share_potential"]) < 0.02, "wind share"
    assert close(R["reconciled_cost_bn"], R["objective_annual_bn"] - R["annual_electricity_bn"] + R["hourly_electricity_bn"])
    assert close(sum(R["hourly_parts_bn"].values()), R["hourly_electricity_bn"])


def test_methane_balance(S):
    """The turbines' methane is supplied inside the annual model: supply covers transport, bio-methanol and turbine
    use, waste biomethane stays within its cap, and the methane assigned covers the verified turbine fuel (2%)."""
    mb = S["methane_balance_twh"]
    supply = mb["waste_biomethane"] + mb["kelp_methane"] + mb["e_methane"]
    use = mb["transport"] + mb["bio_methanol"] + mb["turbines"] + mb["reserve"]
    assert supply >= use - 1e-6, f"methane supply {supply:.3f} < use {use:.3f}"
    assert mb["waste_biomethane"] <= O._base_params()["wch4"]["cap"] + 1e-6, "waste biomethane above cap"
    m = L("reconciled.json")["methane"]
    assert m["assigned_in_annual_model_twh"] >= 0.98 * m["turbine_need_twh"], \
        f"turbine methane assigned {m['assigned_in_annual_model_twh']:.2f} < need {m['turbine_need_twh']:.2f}"


def test_regional_reliability(S):
    """Verification reports unserved energy by grid; grid values add up to the total; each grid's ten-year mean
    is within the 0.002% expected-unserved-energy standard."""
    V = L("verify_hourly.json")["years"]
    grids = next(iter(V.values()))["unserved_mwh_by_node"]
    for y, v in V.items():
        assert abs(sum(v["unserved_mwh_by_node"].values()) - v["unserved_mwh"]) < 1e-3 * max(v["unserved_mwh"], 1), y
    for g in grids:
        u = sum(v["unserved_mwh_by_node"][g] for v in V.values()) / len(V)
        d = sum(v["direct_twh_by_node"][g] for v in V.values()) / len(V) * 1e6
        assert u <= 2e-5 * d, f"{g}: expected unserved {100 * u / d:.4f}%"


def test_regression(S):
    """Headline values of the submitted results (calibrated); update deliberately when the model changes."""
    ref = dict(objective_bn=80.168, ers_km_electrified=5626.5, kelp_total_km2=3000.0, wtw_reduction_pct=92.04)
    for k, v in ref.items():
        assert abs(S[k] - v) <= 0.002 * abs(v), f"regression: {k} = {S[k]:.4f}, reference {v}"
    R = L("reconciled.json")
    for k, v in dict(reconciled_cost_bn=85.30, wtw_reduction_pct=91.81).items():
        assert abs(R[k] - v) <= 0.002 * abs(v), f"regression (reconciled): {k} = {R[k]:.4f}, reference {v}"


def test_scenarios():
    """Removing or forcing options never lowers cost; break-even Brent reproduces system cost; shortfall reported."""
    R = L("scenarios.json")
    assert R["electric_or_biofuel"]["shortfall_twh"] > 0, "electric-or-biofuel case reports its shortfall"
    assert R["ers_none"]["cost_bn"] >= R["central"]["cost_bn"] - 1e-6, "removing an option cannot lower cost"
    assert R["ers_all"]["cost_bn"] >= R["central"]["cost_bn"] - 1e-6, "forcing all corridors cannot lower cost"
    for name, k in R["kelp_sens"].items():
        if name.startswith("hypothetical"):
            continue
        assert k["cost_bn"] >= R["central"]["cost_bn"] - 1e-6, f"kelp restriction {name} lowered cost"
    be = R["fossil_breakeven"]
    f = I.fossil_cost_at_brent(be["brent_usd"], be["cost_2025_bn"], be["cost_oct2026_bn"])
    assert abs(f - be["system_bn"]) < 1e-6, "break-even Brent reproduces the system cost"


def test_feed():
    """All feed cases feasible, amino-acid minima met, no same-species feeding where banned."""
    F = L("feed.json")
    for case, d in F["2050"].items():
        assert d["feasible"], f"feed case {case} infeasible"
        assert all(abs(sum(u.values())) >= 0 for u in d["use_t"].values())
        for sp, aa in d["amino_acids"].items():
            from feed import SPEC
            assert aa["lys"] >= SPEC[sp]["lys"] - 1e-9 and aa["met"] >= SPEC[sp]["met"] - 1e-9, f"amino acids {sp}"
        for sw in d["swaps_t"]:
            a, b = sw.split("->")
            if "own species" not in case:
                assert a != b, f"same-species feeding in {case}"


def main():
    S = L("central.json")
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    fails = 0
    for n, f in tests:
        try:
            f(S) if f.__code__.co_argcount else f()
            print(f"  pass  {n}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL  {n}: {e}")
    print(f"test_model: {len(tests) - fails}/{len(tests)} passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
