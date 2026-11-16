"""Screening test only: this is not chronological (hourly) dispatch, which needs multi-year weather and demand traces
and a regional network model. Winter renewable lulls (southern 'wind droughts'): energy and peak gaps, then a renewable-methane reserve and
backup turbines added to the linear programme and the system re-optimised.

During a lull of 3, 7 or 14 days in June-August, wind runs at 5, 10 or 15% of capacity and solar at 12% (a cloudy
southern winter; daily solar output is assumed shifted within the day by the batteries already in the solution),
electrolysers, air capture and heat storage stop, direct electric loads rise 10% (cabin and battery heating) with a
1.35 peak factor, and 0, 10 or 25% of weekly Australian hydro energy (Snowy Scheme and Tasmania, about 16 TWh/yr) is
reshaped into the lull. Batteries supply 60% of their daily shifting power (shifted solar / 4 h) at the peak. The remaining peak sets
the turbine capacity and the energy gap, at 38% efficiency, a reserve of renewable methane that the LP must produce and
store each year (storage AUD 3/MWh-yr). Iterated until the cost changes by less than AUD 0.01 bn. AEMO's May 2024
eight-day low-wind event averaged a 9.4% wind capacity factor.
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import copy
import json

import optimise as O

HYDRO_TWH = 16.0
SOLAR_CF = 0.12


def gap(S, days, wind_cf, hydro_share, batt_credit=0.6):
    direct_twh = S["electricity_twh"]["vehicles_rail"] + S["electricity_twh"]["refineries_heat"]
    avg = direct_twh / 8.76 * 1.10                      # GW
    peak = avg * 1.35
    batt_gw = batt_credit * S["el_flows_twh"]["pv_shifted"] / (365 * 4) * 1000     # share of battery power firm at the peak
    hydro_gw = HYDRO_TWH / 52 * hydro_share / (days * 24) * 1000 * (days / 7)
    supply_avg = S["wind_gw"] * wind_cf + S["pv_gw"] * SOLAR_CF + hydro_gw
    peak_supply = S["wind_gw"] * wind_cf + batt_gw + hydro_gw
    smr = sum(d["gw"] for d in S["smr"].values()) * 0.95
    e_gap = max(0.0, avg - supply_avg - smr) * days * 24 / 1000     # TWh_e
    p_gap = max(0.0, peak - peak_supply - smr)
    return dict(days=days, wind_cf=wind_cf, hydro_share=hydro_share, batt_credit=batt_credit, demand_gw=avg, peak_gw=peak, battery_gw=batt_gw,
                energy_gap_twh=e_gap, peak_gap_gw=p_gap, methane_twh=e_gap / 0.38)


def with_reserve(days, wind_cf, hydro_share, p0=None, batt_credit=0.6):
    p = copy.deepcopy(p0 or O.base_params())
    S = O.solve(p)
    base = S["objective_bn"]
    last = None
    for _ in range(12):
        g = gap(S, days, wind_cf, hydro_share, batt_credit)
        p["reserve"]["ch4_twh"] = g["methane_twh"]
        p["reserve"]["turbine_gw"] = g["peak_gap_gw"]
        S = O.solve(p)
        if last is not None and abs(S["objective_bn"] - last) < 0.01:
            break
        last = S["objective_bn"]
    return dict(event=f"{days} d, wind {int(wind_cf*100)}%, hydro {int(hydro_share*100)}%, battery credit {int(batt_credit*100)}%",
                days=days, wind_cf=wind_cf, hydro_share=hydro_share, batt_credit=batt_credit, turbine_gw=g["peak_gap_gw"],
                methane_twh=g["methane_twh"], cost_bn=S["objective_bn"], extra_bn=S["objective_bn"] - base,
                kelp_km2=S["kelp_total_km2"], generation_twh=S["generation_total_twh"],
                wtw_reduction_pct=S["wtw_reduction_pct"], waste_ch4=S["fuels_twh"]["waste_biomethane"],
                kelp_ch4=S["fuels_twh"]["kelp_methane"], solution=S)


def run():
    C = O.solve(O.base_params())
    screen = [gap(C, d, w, h) for d in (3, 7, 14) for w in (0.05, 0.10, 0.15) for h in (0.0, 0.10, 0.25)]
    events = [with_reserve(7, 0.10, 0.10), with_reserve(14, 0.10, 0.10), with_reserve(14, 0.05, 0.0)]
    events += [with_reserve(d, w, h, batt_credit=b) for (d, w, h) in ((7, 0.10, 0.10), (14, 0.05, 0.0)) for b in (0.3, 0.0)]
    json.dump(events[0]["solution"], open(O.OUT / "central_with_reserve.json", "w"), indent=1, default=float)
    for e in events:
        e.pop("solution")
    R = dict(screen=screen, events=events, central_cost_bn=C["objective_bn"])
    json.dump(R, open(O.OUT / "adequacy.json", "w"), indent=1, default=float)
    return R


if __name__ == "__main__":
    R = run()
    for e in R["events"]:
        print(e)
    for g in R["screen"][:9]:
        print({k: round(v, 2) for k, v in g.items()})
