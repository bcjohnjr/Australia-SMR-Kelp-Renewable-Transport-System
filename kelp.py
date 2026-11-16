"""Native kelp on the Great Southern Reef: zones, yields, marine-heatwave losses, farm and refinery cost (AUD 2026).

Species. Golden kelp (Ecklonia radiata) dominates the Great Southern Reef from the mid-west coast of Western Australia
to southern Queensland and is farmed in Tasmanian trials; giant kelp (Macrocystis pyrifera) is native to south-east
Tasmania, where seeded-rope cultivation beside salmon pens began in 2018-2020 (Seaweed Solutions CRC-P). Both are
harvested by the cable-guided Grid Harvester (grid_harvester.py).

Yields (t dry ha-1 yr-1) are screening values at three levels: demonstrated (trial-scale, 1.2), design (two-thirds of
the learning target) and learning target (below). The learning targets sit below the fuel-oriented designs of
10-20 t (Greene et al. 2020) because Australian shelf waters are warmer and poorer in nitrate than the north-east
Pacific: the highest values are given to south-east Tasmania (subantarctic water, giant kelp) and the Bonney Coast
(summer upwelling), the lowest to the Leeuwin-Current coast of Western Australia. Each zone loses an expected share of
its yield to marine heatwaves (the 2011 heatwave removed kelp from ~100 km of coast north of Perth and about 43% of
west-coast kelp forest; south-east Tasmania has lost most of its giant kelp forest since the 1940s).

Areas. Farmable areas are screening estimates of nearshore water 10-60 m deep, outside marine parks, ports,
shipping fairways and existing aquaculture leases, from shelf width and coastline length; they are not a GIS and are
used only as upper bounds.

Cost. Farm cost per dry tonne scales from a reference cost at 15 t/ha (today AUD 575, the Canadian study's CAD 520 at
1.09 AUD/CAD; learning case AUD 370, its CAD 340): 65% of it with area (lines, moorings, seeding) and 35% with biomass
(harvest, handling), times an exposure factor for open coasts (reduced by 40% towards 1 in the learning case). Nitrogen not met by natural supply is supplied by depth cycling (grids lowered to the nitracline at night,
AUD 1.75 M per km2 capital today, 0.87 M in the learning case, and 87,000 per km2-yr) or, in the gulfs and Tasmania, by fish-farm nitrogen (IMTA).

Nitrogen demand. Kelp tissue holds about 12 kg N per dry tonne (the N recovered at the refinery), so 1 Mt of dry kelp
removes about 12 kt N/yr. Fish-farm nitrogen is not a fixed share: it is the dissolved N that adjacent finfish
leases release (IMTA_N_T, t N/yr, screening: south-east Tasmanian salmon ~40 kt/yr at ~55 kg dissolved N per tonne,
half of it reachable by kelp lines, ~1.1 kt N/yr; Spencer Gulf kingfish and tuna ~0.75 kt N/yr), divided by the N
demand of the zone's whole area. It covers a few per cent of the demand; the rest must come from natural supply
(nat_n) or depth cycling.

Conservation. Giant kelp marine forests of south-east Australia are an EPBC-listed endangered ecological community
(since August 2012). Farm lines are not natural forest, but any lease in south-east Tasmania would require referral
and assessment under the EPBC Act, and the areas here are upper bounds before that screening.
Refining: whole-kelp hydrothermal liquefaction with hydrotreating (route H of the Canadian model): 1.90 MWh of
hydrocarbon (at most 40% jet), 0.31 MWh of methane, 0.50 MWh of electricity and 0.46 MWh of heat at 150 C per dry
tonne, AUD 230 per dry tonne (learning; 330 today), and recovered N, P and K (12, 2.4, 36 kg per dry tonne).
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
from dataclasses import dataclass

CRF = lambda r, n: r * (1 + r) ** n / ((1 + r) ** n - 1)


@dataclass
class Zone:
    name: str
    species: str
    y_lt: float          # learning-target yield, t dry/ha/yr, before heatwave loss
    mhw: float           # expected annual share of yield lost to marine heatwaves
    nat_n: float         # share of nitrogen demand met by natural supply (or adjacent fish farms)
    exposure: float      # farm cost factor for wave exposure
    area_km2: float      # farmable area (upper bound)
    haul_km: float       # mean wet haul to the refinery
    pool: str            # refinery heat pool
    imta: bool = False   # adjacent finfish leases supply part of the nitrogen
    key: str = ""


ECK, MAC = "Ecklonia radiata (golden kelp)", "Macrocystis pyrifera (giant kelp)"
ZONES = {
    "tas_se": Zone("South-east Tasmania (Storm Bay, D'Entrecasteaux)", MAC, 12.0, 0.10, 0.75, 1.00, 1200, 30, "TAS", True),
    "tas_e": Zone("East Tasmania", MAC, 10.0, 0.12, 0.60, 1.25, 2000, 60, "TAS"),
    "bass": Zone("Bass Strait and Gippsland", ECK, 9.0, 0.05, 0.55, 1.30, 5000, 70, "VIC"),
    "bonney": Zone("Bonney Coast upwelling (Portland-Robe)", ECK, 9.5, 0.04, 0.80, 1.35, 3000, 50, "SE"),
    "sa_gulfs": Zone("Spencer Gulf and Gulf St Vincent", ECK, 6.5, 0.10, 0.45, 0.95, 3500, 80, "SA", True),
    "sa_shelf": Zone("Eyre Peninsula and Kangaroo Island shelf", ECK, 8.0, 0.05, 0.60, 1.35, 5000, 120, "SA"),
    "wa_south": Zone("WA south coast (Albany-Esperance)", ECK, 7.5, 0.06, 0.45, 1.40, 4000, 80, "WA"),
    "wa_west": Zone("WA west coast (Perth-Geraldton)", ECK, 6.0, 0.20, 0.35, 1.15, 4000, 60, "WA"),
    "nsw_south": Zone("NSW south coast (Eden-Jervis Bay)", ECK, 7.0, 0.12, 0.55, 1.25, 1500, 60, "SE"),
}
for _k, _z in ZONES.items():
    _z.key = _k

# ---- observed ocean data (observed_data/kelp_ocean.json; observed.py) replace the screening values ----------------
import copy as _copy
import json as _json
from pathlib import Path as _Path

ZONES_PRIOR = _copy.deepcopy(ZONES)
OCEAN_RULES = dict(
    area="0.5 x sea area 10-100 m deep within 75 km of the zone centre (ETOPO 1'); half assumed unavailable to marine "
         "parks, ports, shipping lanes, cables, fisheries and existing leases (CAPAD marine polygons not used)",
    nat_n="months of the World Ocean Atlas 2023 climatology with mean nitrate >= 1 umol/kg in 0-30 m, divided by 12",
    mhw="max(0.05, 0.7 x share of years 2005-2024 with >= 10 days of NOAA OISST daily SST above the species limit: "
        "20 C giant kelp, 23 C golden kelp)",
    exposure="1 + 0.03 x days per year with maximum significant wave height > 6 m (ERA5 ocean waves 2015-2024)",
)


def _apply_ocean():
    f = _Path(__file__).resolve().parent / "observed_data" / "kelp_ocean.json"
    if not f.exists():
        return {}
    oc = _json.loads(f.read_text())
    used = {}
    for k, z in ZONES.items():
        d = oc[k]
        z.area_km2 = 0.5 * d["area_10_100m_within_75km_km2"]
        z.nat_n = d["months_surface_no3_ge_1"] / 12.0
        z.mhw = max(0.05, 0.7 * d["damaging_year_share_2005_2024"])
        z.exposure = 1.0 + 0.03 * d["days_hs_over_6m_per_yr"]
        used[k] = dict(area_km2=z.area_km2, nat_n=z.nat_n, mhw=z.mhw, exposure=z.exposure)
    return used


OCEAN_USED = _apply_ocean()
DEPLOYMENT_CAP_KM2 = 1000.0   # first-generation cap per zone in every run, including the Monte Carlo; the uncapped
                              # ocean bounds are reported only as a hypothetical case
YIELD_LEVELS = {"demonstrated": lambda z: 1.2, "design": lambda z: z.y_lt * 2 / 3, "learning": lambda z: z.y_lt}


@dataclass
class KelpCost:
    base_aud_t: float = 370.0           # learning case; today 575
    ref_yield: float = 15.0
    area_share: float = 0.65
    depth_cycle_capex_km2: float = 0.87e6   # learning case; today 1.75e6
    depth_cycle_opex_km2: float = 87e3
    depth_cycle_life: float = 15
    imta_capture: float = 1.0           # multiplier on the fish-farm nitrogen reachable by kelp (IMTA_N_T)
    nat_n_scale: float = 1.0            # multiplier on the natural nitrogen share (sensitivity)
    n_kg_t: float = 12.0                # tissue nitrogen, kg N per dry tonne
    haul_aud_t_wet_km: float = 0.035
    dm: float = 0.12
    refinery_aud_t: float = 230.0
    rate: float = 0.04
    exposure_learning: float = 0.6      # (factor - 1) multiplied by this in the learning case; 1.0 today
    fert_aud_kg: tuple = (2.0, 4.0, 1.0)  # N, P, K
    fert_kg_t: tuple = (12.0, 2.4, 36.0)


IMTA_N_T = {"tas_se": 1100.0, "sa_gulfs": 750.0}   # dissolved N from adjacent finfish leases reachable by kelp, t/yr

HTL = dict(hc_mwh=1.90, jet_max=0.40, ch4_mwh=0.313, el_mwh=0.497, heat_mwh=0.46, co2_t=0.25)


def effective_yield(z: Zone, level="learning", scale=1.0):
    return YIELD_LEVELS[level](z) * scale * (1 - z.mhw)


def cost_per_dry_t(z: Zone, c: KelpCost, y_eff: float):
    """Farm, nutrient and haul cost per dry tonne, and refinery cost net of fertiliser credit."""
    expo = 1 + (z.exposure - 1) * c.exposure_learning
    farm = c.base_aud_t * (c.area_share * c.ref_yield / max(y_eff, 0.1) + (1 - c.area_share)) * expo
    t_km2 = y_eff * 100.0
    n_demand_t = t_km2 * z.area_km2 * c.n_kg_t / 1000          # t N/yr for the whole zone area
    imta = (IMTA_N_T.get(z.key, 0.0) * c.imta_capture / n_demand_t) if (z.imta and n_demand_t > 0) else 0.0
    nat = min(1.0, z.nat_n * c.nat_n_scale + imta)
    dc_ann = c.depth_cycle_capex_km2 * CRF(c.rate, c.depth_cycle_life) + c.depth_cycle_opex_km2
    nutrient = dc_ann * (1 - nat) / t_km2
    haul = c.haul_aud_t_wet_km * z.haul_km / c.dm
    fert = sum(p * k for p, k in zip(c.fert_aud_kg, c.fert_kg_t))
    return dict(farm=farm, nutrient=nutrient, haul=haul, refinery=c.refinery_aud_t, fert_credit=fert,
                n_demand_kt=n_demand_t / 1000, imta_share=imta, natural_share=min(1.0, z.nat_n * c.nat_n_scale),
                total=farm + nutrient + haul + c.refinery_aud_t - fert)


def zone_table(level="learning", c: KelpCost = KelpCost(), scale=1.0):
    rows = {}
    for k, z in ZONES.items():
        y = effective_yield(z, level, scale)
        cc = cost_per_dry_t(z, c, y)
        fuel = HTL["hc_mwh"] + HTL["ch4_mwh"]
        rows[k] = dict(name=z.name, species=z.species, pool=z.pool, area_km2=z.area_km2, yield_eff=y,
                       dry_t_km2=y * 100, cost_aud_t=cc["total"], parts=cc, aud_per_mwh_fuel=cc["total"] / fuel,
                       n_kg_km2=y * 100 * c.n_kg_t, imta_share=cc["imta_share"], natural_share=cc["natural_share"])
    return rows


if __name__ == "__main__":
    for k, r in zone_table().items():
        print(f"{k:10s} y={r['yield_eff']:.2f} cost={r['cost_aud_t']:.0f} AUD/dt  {r['aud_per_mwh_fuel']:.0f} AUD/MWh  {r['parts']}")
