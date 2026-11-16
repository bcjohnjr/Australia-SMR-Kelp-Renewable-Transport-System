"""Figures 1-6 and Supplementary Figures (PNG at 300 dpi and vector PDF). Each function returns its source data."""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, FancyArrowPatch
from matplotlib.lines import Line2D
import matplotlib.patheffects as pe
import textwrap
import numpy as np

import geo
import inputs as I
import kelp as K
import optimise as O

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
FIG = HERE / "paper_figures"
FIG.mkdir(exist_ok=True)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
SURF = "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5, "axes.edgecolor": MUTED, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titlesize": 8.5, "axes.titleweight": "bold", "legend.frameon": False,
                     "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white"})
L = lambda f: json.load(open(OUT / f))


HALO = [pe.withStroke(linewidth=2.4, foreground="white")]


def save(fig, name):
    fig.savefig(FIG / f"{name}.png", dpi=300, bbox_inches="tight")
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def panel(ax, letter, title):
    ax.set_title(title, loc="left", pad=6)
    ax.text(-0.13, 1.06, letter.upper(), transform=ax.transAxes, fontsize=10, fontweight="bold", va="bottom")


def bar_ends(ax):
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)


# ------------------------------------------------------------------------------------------ Figure 1 map
def fig1():
    C, R, CA, A = L("central.json"), L("scenarios.json"), L("cascade.json"), L("feed.json")
    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    ax.set_facecolor("#e6eef4")
    for nm, pts in geo.FEED_BELTS.items():
        ax.add_patch(Polygon(pts, closed=True, fc="#f6e7b8", ec="none", zorder=1))
    ax.add_patch(Polygon(geo.MAINLAND, closed=True, fc="#f7f6f2", ec="#7d7c77", lw=0.6, zorder=0.5))
    for nm, pts in geo.FEED_BELTS.items():
        ax.add_patch(Polygon(pts, closed=True, fc="#f3d98a", ec="#c9a227", lw=0.4, alpha=0.75, hatch="////", zorder=1.2))
    for pts in geo.ISLANDS.values():
        ax.add_patch(Polygon(pts, closed=True, fc="#f7f6f2", ec="#7d7c77", lw=0.6, zorder=0.5))
    for b in geo.STATE_BORDERS:
        x, y = zip(*b)
        ax.plot(x, y, color="#bdbcb6", lw=0.5, zorder=1.3)
    # currents
    def arrow(pts, label, xy):
        for a, b in zip(pts, pts[1:]):
            ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=7, color="#7fa7c6", lw=1.0, zorder=0.8))
        ax.text(*xy, label, color="#4f7fa6", fontsize=6.3, style="italic", zorder=5, path_effects=HALO)
    arrow([(111.6, -21.5), (112.0, -27.5), (113.2, -33.2), (116.5, -36.3), (124.0, -35.6)], "Leeuwin\nCurrent", (108.4, -19.6))
    arrow([(159.4, -17.0), (159.3, -30.0), (158.3, -36.8), (154.6, -41.6)], "East Australian\nCurrent", (155.6, -14.6))
    ax.text(137.4, -41.4, "Bonney\nupwelling", color="#4f7fa6", fontsize=6.2, style="italic", path_effects=HALO)
    for t, xy in (("INDIAN OCEAN", (108.6, -13.2)), ("SOUTHERN OCEAN", (126.0, -41.0)), ("TASMAN SEA", (153.2, -44.0)),
                  ("CORAL SEA", (150.5, -12.5)), ("ARAFURA SEA", (133.0, -9.6)), ("TIMOR SEA", (121.6, -12.0)),
                  ("Great Australian Bight", (124.4, -35.2))):
        ax.text(*xy, t, color="#5d86a8", fontsize=6.6 if t.isupper() else 6.2, style="italic", alpha=0.95,
                path_effects=HALO, zorder=5)
    # highways
    ers = C["ers_twh"]
    for c, pts in geo.HIGHWAYS.items():
        x, y = zip(*pts)
        if C["ers_built"].get(c, 0):
            ax.plot(x, y, color=SERIES[0], lw=2.4, solid_capstyle="round", zorder=3)
        else:
            ax.plot(x, y, color="#6d6c68", lw=1.2, ls=(0, (1.5, 1.8)), zorder=3)
    # kelp zones
    kc = C["kelp_km2"]
    forced = R["kelp_forced"]
    for z, (x, y) in geo.KELP_CENTROIDS.items():
        a = kc.get(z, 0.0)
        if a >= 50:
            ax.scatter(x, y, s=60 + a / 8, color=SERIES[2], alpha=0.8, edgecolor="white", lw=1.2, zorder=4)
        else:
            ax.scatter(x, y, s=70, facecolor="none", edgecolor=SERIES[2], lw=1.0, ls=(0, (2, 1.5)), zorder=4)
    _n = sum(1 for v in kc.values() if v >= 50)
    ax.annotate(f"Kelp, {sum(v for v in kc.values() if v >= 50):,.0f} km²\n({_n} zones, capped;\nhypothetical)", (148.05, -43.55), (150.2, -47.9),
                fontsize=6.3, color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.5), zorder=6, path_effects=HALO)
    ax.text(108.8, -43.7, "Dashed: kelp zones not chosen; forcing 1,000 km²\ninto one adds AUD "
            f"{min(v['extra_bn'] for v in forced.values()):.2f}-{max(v['extra_bn'] for v in forced.values()):.2f} bn yr⁻¹",
            fontsize=6.1, color=INK2, zorder=6, va="bottom", path_effects=HALO)
    # SMR sites with leader lines
    lab_xy = {"Port Augusta": (124.2, -27.9), "Muja": (117.8, -39.6), "Loy Yang": (149.7, -39.2),
              "Liddell": (154.0, -30.9), "Mount Piper": (154.0, -34.4), "Tarong": (154.3, -26.6),
              "Callide": (154.3, -23.6), "Gladstone (test)": (154.3, -20.5)}
    lab_name = {"Muja": "Muja (steam to\nWorsley alumina)", "Gladstone (test)": "Gladstone*"}
    for n, d in CA["sites"].items():
        s = I.SITES[n]
        mk = "s" if not s["coalition"] else "o"
        ax.scatter(s["lon"], s["lat"], marker=mk, s=46, color=SERIES[1], edgecolor=INK, lw=0.7, zorder=7)
        ax.annotate(f"{lab_name.get(n, n)}\n{d['npv_bn']:+.1f} | {CA['breakeven_module_bn'][n]:.1f}",
                    (s["lon"], s["lat"]), lab_xy[n], fontsize=5.9, color=INK, zorder=8, linespacing=1.05,
                    path_effects=HALO, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.5, shrinkA=1, shrinkB=3))
    # hubs
    for n, ((x, y), lxy, txt) in geo.HUBS.items():
        ax.scatter(x, y, marker="^", s=28, color=SERIES[6], edgecolor="white", lw=0.6, zorder=7)
        if lxy:
            ax.annotate(txt, (x, y), lxy, fontsize=5.9, color=SERIES[6], zorder=8, linespacing=1.05,
                        path_effects=HALO, arrowprops=dict(arrowstyle="-", color=SERIES[6], lw=0.5, shrinkA=1, shrinkB=3))
    ax.set_xlim(108.0, 160.0)
    ax.set_ylim(-52.0, -8.5)
    ax.set_aspect(1 / math.cos(math.radians(28)))
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(True)
        sp.set_color(MUTED)
    h = [Line2D([], [], color=SERIES[0], lw=2.4, label="Highway electrified with catenary"),
         Line2D([], [], color="#6d6c68", lw=1.2, ls=(0, (1.5, 1.8)), label="Battery trucks and charging hubs"),
         Line2D([], [], marker="o", ls="", color=SERIES[2], ms=7, alpha=0.8, label="Kelp farms in the 2050 solution"),
         Line2D([], [], marker="o", ls="", mfc="none", mec=SERIES[2], ms=7, label="Kelp zone not chosen"),
         Line2D([], [], marker="o", ls="", color=SERIES[1], mec=INK, ms=6,
                label="SMR site (2 modules): NPV | break-even, AUD bn"),
         Line2D([], [], marker="s", ls="", color=SERIES[1], mec=INK, ms=6, label="*Test site, 1 module"),
         Line2D([], [], marker="^", ls="", color=SERIES[6], ms=6, label="Heat and seafood users"),
         plt.Rectangle((0, 0), 1, 1, fc="#f3d98a", ec="#c9a227", hatch="////", label="Inland fish-feed crop belts")]
    ax.legend(handles=h, loc="lower left", bbox_to_anchor=(0.005, 0.005), fontsize=5.9, ncol=2, frameon=True,
              framealpha=0.95, facecolor="white", edgecolor=GRID, borderpad=0.5, columnspacing=1.0)
    ax.set_title("Australia's fossil-free transport system in 2050 and the transition SMR sites", loc="left", fontsize=8.5)
    save(fig, "Fig1_system_map")
    return dict(kelp_km2=kc, ers_twh=ers, sites={n: dict(npv_bn=d["npv_bn"], breakeven_bn=CA["breakeven_module_bn"][n],
                                                         lon=I.SITES[n]["lon"], lat=I.SITES[n]["lat"])
                                              for n, d in CA["sites"].items()},
                corridors={c: dict(km=R["ers_corridors"][c]["km"], chosen_twh=ers.get(c, 0)) for c in geo.HIGHWAYS})


# ------------------------------------------------------------------------------------------ Figure 2
SEG_LABEL = {"ldv_petrol": "Petrol cars", "ldv_diesel": "Diesel utes, SUVs, vans", "hdv": "Trucks and buses",
             "rail": "Rail", "mining": "Mining", "farm": "Farm machinery", "construction": "Construction",
             "aviation": "Aviation (incl. international)", "shipping": "Shipping"}


def fig2():
    C = L("central.json")
    D = C["demand_twh"]
    carriers = [("el", "Battery and grid electric"), ("ers", "Catenary highways"), ("dropin", "Drop-in diesel and petrol"),
                ("jet", "Renewable jet"), ("ethanol", "Ethanol"), ("methane", "Methane"), ("methanol", "Methanol"),
                ("ammonia", "Ammonia")]
    rows = {s: {k: 0.0 for k, _ in carriers} for s in D}
    for key, t in C["end_use_twh"].items():
        s, o = key.split("|")
        rows[s][O.OPTIONS[s][o][0]] += t
    rows["hdv"]["ers"] = sum(C["ers_twh"].values())
    fig = plt.figure(figsize=(7.2, 6.2))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.05, 1], hspace=0.75, wspace=0.42)
    ax = fig.add_subplot(gs[0, :])
    order = sorted(D, key=lambda s: D[s])
    y = np.arange(len(order))
    left = np.zeros(len(order))
    for i, (k, lab) in enumerate(carriers):
        v = np.array([rows[s][k] for s in order])
        if v.sum() < 0.01:
            continue
        ax.barh(y, v, left=left, color=SERIES[i], edgecolor="white", lw=1.0, height=0.62, label=lab)
        left += v
    for yi, s in zip(y, order):
        ax.text(D[s] + 2, yi, f"{D[s]:.0f}", va="center", fontsize=6.5, color=INK2)
    ax.set_yticks(y, [SEG_LABEL[s] for s in order])
    ax.set_xlabel("Fossil energy replaced, TWh yr⁻¹ (2025 sales)")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.legend(ncol=4, fontsize=6.3, loc="upper center", bbox_to_anchor=(0.45, -0.17))
    panel(ax, "a", f"All {sum(D.values()):.0f} TWh of transport fuel replaced")
    # b fuels by source
    ax = fig.add_subplot(gs[1, 0])
    F = C["fuels_twh"]
    srcs = [("Electrofuels (FT)", F["efuel_ft_wind"] + F["efuel_ft_solar"]), ("Cereal straw FT", F["straw_ft"]),
            ("Waste biomethane", F["waste_biomethane"]), ("Canola HVO", F["canola_hvo"]),
            ("Forest and cane residue HTL", F["forest_htl"] + F["cane_htl"]), ("Sorghum and cane ethanol", F["ethanol"]),
            ("Bio- and e-methanol", F["bio_methanol"] + F["e_methanol"]), ("Tallow and UCO HEFA", F["hefa"]),
            ("e-Ammonia", F["e_ammonia"]), ("Tasmanian kelp", F["kelp_hc"] + F["kelp_methane"])]
    if F.get("e_methane", 0.0) > 0.05:
        srcs.append(("Synthetic methane", F["e_methane"]))
    srcs.sort(key=lambda t: t[1])
    ax.barh(range(len(srcs)), [v for _, v in srcs], color=SERIES[0], height=0.62)
    for i, (_, v) in enumerate(srcs):
        ax.text(v + 1.5, i, f"{v:.1f}", va="center", fontsize=6.3, color=INK2)
    ax.set_yticks(range(len(srcs)), [n for n, _ in srcs], fontsize=6.6)
    ax.set_xlabel("Fuel produced, TWh yr⁻¹")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    panel(ax, "b", "Liquid and gaseous fuels by source")
    # c electricity
    ax = fig.add_subplot(gs[1, 1])
    E = C["electricity_twh"]
    REC = L("reconciled.json")
    PH = REC["portfolio_hourly"]
    G = dict(wind=PH["wind_twh_potential"], pv=PH["pv_twh_potential"])
    gen = [("Wind", G["wind"]), ("Solar PV", G["pv"])]
    use = [("Vehicles, rail, catenary", E["vehicles_rail"]), ("Electrolysers", E["efuels"]), ("Air capture", E["dac"]),
           ("Refineries and heat", E["refineries_heat"] + E["heat_storage"])]
    for xi, items, offs in ((0, gen, 0), (1, use, 2)):
        b = 0
        for j, (n, v) in enumerate(items):
            ax.bar(xi, v, bottom=b, color=SERIES[(j + offs) % 8], edgecolor="white", lw=1.0, width=0.55, label=n)
            b += v
        ax.text(xi, b + 6, f"{b:.0f}", ha="center", fontsize=6.5, color=INK2)
    ax.set_xticks([0, 1], ["Available\n(incl. curtailed)", "Used (incl. losses)"])
    ax.set_ylabel("TWh yr⁻¹")
    bar_ends(ax)
    ax.legend(fontsize=6.0, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    panel(ax, "c", f"{PH['wind_gw']:.0f} GW wind, {PH['pv_gw']:.0f} GW solar (hourly fleet)")
    save(fig, "Fig2_complete_replacement")
    return dict(segments=rows, demand=D, fuels=dict(srcs), generation=G, uses=dict(use))


# ------------------------------------------------------------------------------------------ Figure 3
def fig3():
    CA = L("cascade.json")
    W = CA["water"]
    sites = list(CA["sites"])
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 3.2), gridspec_kw=dict(width_ratios=[1.45, 1], wspace=0.45))
    ax = axs[0]
    parts = [("el_twh", "Electricity sold"), ("steam_twh", "150-180 °C steam: alumina, ethanol, kelp, mills"),
             ("low_twh", "70-80 °C: distillation (MED) and greenhouses"), ("reject_twh", "38 °C MED reject: greenhouses, RAS seafood")]
    x = np.arange(len(sites))
    b = np.zeros(len(sites))
    for i, (k, lab) in enumerate(parts):
        v = np.array([CA["sites"][s]["first_year"][k] for s in sites])
        ax.bar(x, v, bottom=b, color=SERIES[i], edgecolor="white", lw=1.0, width=0.66, label=lab)
        b += v
    for xi, s in zip(x, sites):
        wml = CA["sites"][s]["first_year"]["water_ml_day"]
        if wml > 1:
            ax.text(xi, b[xi] + 0.1, f"{wml:.0f}\nML/d", ha="center", fontsize=5.8, color=INK2)
    ax.set_xticks(x, [s.replace(" (test)", "*") for s in sites], rotation=35, ha="right")
    ax.set_ylabel("Delivered in first year, TWh yr⁻¹")
    ax.set_ylim(0, b.max() * 1.15)
    bar_ends(ax)
    ax.legend(fontsize=6.0, loc="upper left", bbox_to_anchor=(-0.05, -0.32), ncol=2)
    panel(ax, "a", "Heat cascade at each SMR site")
    ax = axs[1]
    names = list(W["cases"])
    short = ["SWRO, grid power", "MED, SMR 75 °C heat", "MED + Port Augusta\nreject-heat sales",
             "MED, solar-thermal", "MED, gas heat"]
    vals = [W["cases"][n]["total"] for n in names]
    cols = [SERIES[0] if i == 0 else SERIES[2] for i in range(len(names))]
    ax.barh(range(len(names)), vals, color=cols, height=0.6)
    for i, v in enumerate(vals):
        ax.text(v + 0.08, i, f"{v:.2f}", va="center", fontsize=6.5, color=INK2)
    ax.set_yticks(range(len(names)), short, fontsize=6.5)
    ax.invert_yaxis()
    ax.set_xlabel("Levelized water cost, AUD m⁻³")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(vals) * 1.18)
    panel(ax, "b", "Distilled versus reverse-osmosis water")
    save(fig, "Fig3_heat_cascade")
    return dict(sites={s: {k: CA["sites"][s]["first_year"][k] for k, _ in parts + [("water_ml_day", "")]} for s in sites},
                water={n: W["cases"][n] for n in names},
                breakeven_reject_share=W["breakeven_reject_share_vs_heat_pump"])


# ------------------------------------------------------------------------------------------ Figure 4
def fig4():
    R, CA = L("scenarios.json"), L("cascade.json")
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 3.1), gridspec_kw=dict(width_ratios=[1, 1.5], wspace=0.35))
    ax = axs[0]
    sw = R["smr_capex_sweep"]
    xs = [r["module_bn"] for r in sw]
    ax.plot(xs, [1000 * r["saving_bn"] for r in sw], color=SERIES[1], lw=2, marker="o", ms=4)
    ax.axvline(4.6, color=MUTED, lw=0.8, ls=(0, (3, 2)))
    ax.text(4.5, 195, "GenCost 2050\nAUD 4.6 bn", fontsize=6, color=INK2, ha="right", va="top")
    be = R["smr_breakeven_module_bn"]
    ax.text(1.4, 140, f"Break-even (continuous):\neast {be['east']:.2f}, SA {be['sa']:.2f},\nWA {be['wa']:.2f} AUD bn",
            fontsize=6.2, color=INK)
    wm = R["smr_whole_modules"]["4.6"]["rows"]
    best = [r for r in wm if r["sites"] > 0][0]
    ax.text(1.4, 60, f"Best whole fleet (1 site):\n{best['saving_bn']*1000:+.0f} M yr⁻¹", fontsize=6.2, color=INK)
    ax.set_xlabel("Module capital, AUD bn per 300 MWe")
    ax.set_ylabel("System saving, AUD M yr⁻¹")
    ax.set_ylim(-10, 200)
    bar_ends(ax)
    panel(ax, "a", "SMRs in the 2050 national optimum")
    ax = axs[1]
    sites = list(CA["sites"])
    var = [("central", "Central (AUD 4.8 bn modules,\n1.75 bn site)"), ("brownfield site AUD 0.9 bn", "Brownfield site 0.9 bn"),
           ("modules AUD 3.0 bn, site 0.9 bn", "Modules 3.0 bn, site 0.9 bn"),
           ([k for k in CA["consistent"] if "capacity AUD" in k][0], "National shadow prices throughout")]
    w = 0.2
    x = np.arange(len(sites))
    for i, (k, lab) in enumerate(var):
        ax.bar(x + (i - 1.5) * w, [CA["variants"][k][s] for s in sites], width=w * 0.92, color=SERIES[i], label=lab)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_xticks(x, [s.replace(" (test)", "*") for s in sites], rotation=35, ha="right")
    ax.set_ylabel("Net present value, AUD bn")
    bar_ends(ax)
    ax.legend(fontsize=6.0, ncol=2, loc="lower left", bbox_to_anchor=(0.0, 1.0))
    ax.set_title("")
    ax.text(-0.09, 1.25, "B", transform=ax.transAxes, fontsize=10, fontweight="bold")
    ax.text(0.0, 1.25, "Transition site NPV", transform=ax.transAxes, fontsize=8.5, fontweight="bold")
    save(fig, "Fig4_smr_economics")
    return dict(sweep=sw, breakeven=be, whole_modules=wm[:6],
                npv={k: {s: CA["variants"][k][s] for s in sites} for k, _ in var})


# ------------------------------------------------------------------------------------------ Figure 5
def fig5():
    F, CP = L("feed.json"), L("coproduction.json")
    fig = plt.figure(figsize=(7.2, 5.9))
    gs = fig.add_gridspec(2, 2, hspace=0.62, wspace=0.95)
    cases = ["no swap", "cross-species swap", "swap, own species allowed", "fish-free, no swap", "fish-free, cross-species swap"]
    lab = ["No\nswap", "Cross-\nspecies\nswap", "Swap\nincl. own\nspecies", "Fish-\nfree, no\nswap", "Fish-\nfree +\nswap"]
    ax = fig.add_subplot(gs[0, 0])
    d50 = F["2050"]
    wild = [d50[c]["wild_fish_t"] / 1e3 for c in cases]
    ax.bar(range(5), wild, color=SERIES[0], width=0.6)
    for i, c in enumerate(cases):
        ax.text(i, wild[i] + 0.4, f"{d50[c]['cost_aud_m']:.0f}", ha="center", fontsize=6.2, color=INK2)
    ax.set_xticks(range(5), lab, fontsize=6.0)
    ax.set_ylabel("Wild fish used, kt yr⁻¹")
    ax.set_ylim(0, max(wild) * 1.25 + 1)
    ax.text(0.98, 0.95, "labels: feed cost, AUD M yr⁻¹", transform=ax.transAxes, ha="right", fontsize=6.0, color=INK2)
    bar_ends(ax)
    panel(ax, "a", f"Feed for {sum(F['2050']['no swap']['feed_t'].values())/1e3:.0f} kt in 2050")
    ax = fig.add_subplot(gs[0, 1])
    crops = ["lupin", "canola (meal and oil)", "faba protein concentrate", "wheat gluten", "wheat", "DHA canola oil"]
    cl = ["Lupin (WA)", "Canola meal and oil", "Faba protein", "Wheat gluten", "Wheat binder", "DHA canola"]
    sel = ["cross-species swap", "fish-free, cross-species swap", "no swap"]
    b = np.zeros(len(sel))
    for i, c in enumerate(crops):
        v = np.array([d50[s]["cropland_ha"].get(c, 0) / 1e3 for s in sel])
        ax.bar(range(len(sel)), v, bottom=b, color=SERIES[i], edgecolor="white", lw=1.0, width=0.6, label=cl[i])
        b += v
    ax.set_xticks(range(len(sel)), ["Swap", "Fish-free\n+ swap", "No swap"], fontsize=6.4)
    ax.set_ylabel("Inland cropland, kha")
    bar_ends(ax)
    ax.legend(fontsize=5.9, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    panel(ax, "b", "Inland Australia grows the feed")
    ax = fig.add_subplot(gs[1, 0])
    sp = ["salmon", "prawn", "barramundi", "kingfish"]
    M = np.zeros((4, 4))
    for k, v in d50["cross-species swap"]["swaps_t"].items():
        a, r = k.split("->")
        M[sp.index(a), sp.index(r)] = v / 1e3
    im = ax.imshow(M, cmap="Blues", vmin=0, vmax=max(M.max(), 1))
    for i in range(4):
        for j in range(4):
            if i == j:
                ax.text(j, i, "banned", ha="center", va="center", fontsize=5.8, color=MUTED)
            elif M[i, j] > 0.01:
                ax.text(j, i, f"{M[i, j]:.1f}", ha="center", va="center", fontsize=6.4,
                        color="white" if M[i, j] > 0.5 * M.max() else INK)
    ax.set_xticks(range(4), ["Salmon", "Prawn", "Barra", "Kingfish"], fontsize=6.4)
    ax.set_yticks(range(4), ["Salmon", "Prawn", "Barra", "Kingfish"], fontsize=6.4)
    ax.set_xlabel("Fed to")
    ax.set_ylabel("By-product meal and oil from")
    for s in ax.spines.values():
        s.set_visible(False)
    panel(ax, "c", "Cross-species meal swap, kt yr⁻¹")
    ax = fig.add_subplot(gs[1, 1])
    items = [("QLD pond prawns", CP["prawn_pond"]["margin_aud_kg"], 0),
             ("RAS prawns, cascade heat", CP["prawn_ras"]["cascade reject heat"]["margin_aud_kg"], 2),
             ("RAS prawns, heat pump", CP["prawn_ras"]["heat pump"]["margin_aud_kg"], 2),
             ("RAS prawns, gas", CP["prawn_ras"]["gas boiler"]["margin_aud_kg"], 2),
             ("RAS barramundi, cascade heat", CP["barra_ras"]["cascade reject heat"]["margin_aud_kg"], 1),
             ("RAS barramundi, gas", CP["barra_ras"]["gas boiler"]["margin_aud_kg"], 1)]
    for pr in CP["salmon"]["rows"]:
        items.append((f"Tas salmon + robots, AUD {pr['price']:.0f}/kg", pr["net_aud_m"] / 50.0, 3))
    for pr in CP["kingfish"]["rows"][:2]:
        items.append((f"Kingfish + robots, AUD {pr['price']:.0f}/kg", pr["net_aud_kg"], 6))
    ax.barh(range(len(items)), [v for _, v, _ in items], color=[SERIES[c] for _, _, c in items], height=0.62)
    for i, (_, v, _) in enumerate(items):
        ax.text(v + 0.1, i, f"{v:.2f}", va="center", fontsize=5.9, color=INK2)
    ax.set_yticks(range(len(items)), [n for n, _, _ in items], fontsize=5.9)
    ax.invert_yaxis()
    ax.set_xlabel("Margin, AUD kg⁻¹")
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(v for _, v, _ in items) * 1.2)
    panel(ax, "d", "Seafood margins")
    save(fig, "FigS8_feed_and_seafood")
    return dict(wild_kt=dict(zip(cases, wild)), cost_aud_m={c: d50[c]["cost_aud_m"] for c in cases},
                cropland_kha={s: {c: d50[s]["cropland_ha"].get(c, 0) / 1e3 for c in crops} for s in sel},
                swap_kt=M.tolist(), margins=[(n, v) for n, v, _ in items])


# ------------------------------------------------------------------------------------------ Figure 6
def fig6():
    R, CP, MC, C = L("scenarios.json"), L("coproduction.json"), L("montecarlo.json"), L("central.json")
    fig, axs = plt.subplots(2, 2, figsize=(7.2, 5.6), gridspec_kw=dict(hspace=0.6, wspace=0.6))
    ax = axs[0, 0]
    rows = R["ers_corridors"]
    names = sorted(rows, key=lambda c: rows[c]["aud_per_mwh"])
    v = [rows[c]["aud_per_mwh"] for c in names]
    cols = [SERIES[0] if rows[c]["built"] else "#b9b8b2" for c in names]
    ax.barh(range(len(names)), v, color=cols, height=0.6)
    thr = C["shadow_aud_mwh"]["dropin"] + 20 - O.ERS_PREMIUM - O.ERS_RATIO * C["shadow_aud_mwh"]["el_direct"]
    ax.text(0.97, 0.80, "Battery trucks take up to 85%\nof heavy-vehicle energy;\ncatenary fills the rest\nfrom the cheapest corridors",
            transform=ax.transAxes, fontsize=5.8, color=INK2, ha="right", va="center", linespacing=1.05)
    ax.set_yticks(range(len(names)), [n.split(" (")[0] + f" ({rows[n]['km']:,.0f} km)" for n in names], fontsize=6.2)
    ax.invert_yaxis()
    ax.set_xlabel("Catenary cost, AUD per MWh of diesel replaced")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    panel(ax, "a", f"Highways: {C['ers_km_electrified']:,.0f} km built")
    ax = axs[0, 1]
    SE = L("dispatch_series.json")
    t = np.arange(len(SE["wind"])) * SE["step_h"] / 24.0
    stack = [("Wind", np.array(SE["wind"]), SERIES[0]), ("Solar", np.array(SE["pv"]), SERIES[3]),
             ("Battery", np.array(SE["battery"]), SERIES[2]), ("Turbines", np.array(SE["turbine"]), SERIES[1])]
    base = np.zeros_like(t)
    for lab, y, col in stack:
        ax.fill_between(t, base, base + y, color=col, lw=0, alpha=0.9, label=lab, step="post")
        base = base + y
    direct = np.array(SE["direct"]) + np.array(SE["managed"])
    flex = np.array(SE["electrolyser"]) + np.array(SE["dac"]) + np.array(SE["charge"])
    ax.step(t, direct, where="post", color=INK, lw=0.9, label="Direct loads")
    ax.step(t, direct + flex, where="post", color=INK, lw=0.6, ls=(0, (2, 1.5)), label="+ electrolysers, storage")
    ax.set_xlim(0, SE["days"])
    ax.set_xticks(range(0, SE["days"] + 1, 2))
    ax.set_ylim(0, max(base.max(), (direct + flex).max()) * 1.32)
    ax.set_xlabel(f"Days from {SE['start_utc'][:10]} (weakest {SE['days']} days, NEM)")
    ax.set_ylabel("GW")
    ax.legend(fontsize=5.4, frameon=False, ncol=3, loc="upper left", handlelength=1.0, columnspacing=0.8,
              borderaxespad=0.1)
    bar_ends(ax)
    panel(ax, "b", "Hourly test: winter lull")
    ax = axs[1, 0]
    CAL = json.load(open(OUT.parent / "calibration.json"))
    DSP = L("dispatch.json")
    items = [("Annual model,\nbefore", CAL["annual_uncalibrated"]["direct"], "#9e9d98"),
             ("Hourly, with\nelectrolysers", CAL["hourly_pass2"]["direct"], SERIES[0]),
             ("Same energy,\ndaily-flexible", L("dispatch_daily.json")["design"]["price_direct_aud_mwh"], SERIES[1]),
             ("Same energy,\nflat demand", L("dispatch_flat.json")["design"]["price_direct_aud_mwh"], SERIES[5]),
             ("Hourly, direct\nloads only", CAL["inflexible"]["price_direct_aud_mwh"], SERIES[2]),
             ("Direct only,\n7% finance", L("dispatch_inflexible_r7.json")["design"]["price_direct_aud_mwh"], SERIES[4]),
             ("Annual model,\ncalibrated", CAL["annual_prices_after"]["direct"], SERIES[6])]
    ys = np.arange(len(items))
    ax.barh(ys, [v for _, v, _ in items], color=[c for _, _, c in items], height=0.6)
    ax.axvspan(141, 152, color=SERIES[7], alpha=0.18, lw=0)
    ax.axvspan(120, 130, color=SERIES[7], alpha=0.10, lw=0)
    ax.text(136, -1.52, "GenCost 2050, whole grid", fontsize=4.9, color=SERIES[7], ha="center", va="top")
    ax.text(146.5, -1.1, "incl.\ntrans.", fontsize=4.9, color=SERIES[7], ha="center", va="top", linespacing=1.0)
    ax.text(125, -1.1, "excl.\ntrans.", fontsize=4.9, color=SERIES[7], ha="center", va="top", linespacing=1.0)
    for y_, (_, v, _) in zip(ys, items):
        ax.text(v - 3, y_, f"{v:.0f}", ha="right", va="center", fontsize=6.4, color="white", fontweight="bold")
    ax.set_yticks(ys, [n.replace("\n", " ") for n, _, _ in items], fontsize=6.0)
    ax.set_ylim(len(items) - 0.4, -1.55)
    ax.set_xlim(0, 168)
    ax.set_xlabel("Direct-load electricity, AUD/MWh")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    panel(ax, "c", "Firmed electricity cost")
    ax = axs[1, 1]
    be = np.array([r.get("breakeven_brent_reconciled", r["breakeven_brent"]) for r in MC["rows"]])
    ax.hist(be, bins=30, color=SERIES[6], alpha=0.85, edgecolor="white", lw=0.5)
    top = ax.get_ylim()[1] * 1.45
    ax.set_ylim(0, top)
    I_ = __import__("inputs")
    s = MC["summary"]
    for val, lab, col, ha, yl in ((I_.BRENT_USD_BBL["avg2025"], "2025\naverage", INK2, "left", 0.80),
                                  (I_.BRENT_USD_BBL["oct2026"], "Oct\n2026", SERIES[7], "right", 0.80),
                                  (R["fossil_breakeven"]["reconciled_brent_usd"], "central\ncase", SERIES[0], "right", 0.62)):
        ax.axvline(val, ymax=yl + 0.10, color=col, lw=1.1, ls=(0, (3, 2)))
        ax.text(val + (1.5 if ha == "left" else -1.5), top * yl, lab, fontsize=5.9, color=col, ha=ha, va="bottom",
                linespacing=1.0, path_effects=HALO)
    ax.set_xlim(55, 165)
    ax.set_yticks([t for t in ax.get_yticks() if 0 <= t <= top * 0.6])
    ax.set_xlabel("Break-even Brent oil price, US$ per barrel")
    ax.set_ylabel("Draws (of 1,000)")
    bar_ends(ax)
    panel(ax, "d", f"Break-even oil: median US${s['breakeven_reconciled_median']:.0f}")
    save(fig, "Fig5_highways_firming_oil")
    return dict(corridors={n: rows[n] for n in names}, winter_window=SE,
                firmed_cost=[dict(case=n.replace("\n", " "), aud_mwh=v) for n, v, _ in items],
                gencost_2050_aud_mwh=dict(incl_transmission=[141, 152], excl_transmission=[120, 130]),
                montecarlo_summary=s)


# ------------------------------------------------------------------------------------------ Supplementary figures
def sfig_illustrations():
    import matplotlib.image as mpimg
    for k, f in (("FigS1_grid_harvester_top", "grid_harvester_top.jpg"), ("FigS2_grid_harvester_side", "grid_harvester_side.jpg")):
        img = mpimg.imread(HERE / "illustrations" / f)
        fig, ax = plt.subplots(figsize=(7.2, 7.2 * img.shape[0] / img.shape[1]))
        ax.imshow(img)
        ax.axis("off")
        save(fig, k)


def sfig_levers():
    R = L("scenarios.json")
    rows = R["levers"]
    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    v = [r["cost_bn"] for r in rows]
    ax.plot(range(len(v)), v, color=SERIES[0], lw=2, marker="o", ms=4)
    for i, r in enumerate(rows):
        ax.text(i, v[i] + 1.2, f"{v[i]:.1f}", ha="center", fontsize=6.4)
    C = L("central.json")
    for val, lab in ((C["fossil_cost_bn"]["avg2025"], "fossil fuel at 2025 prices"),
                     (C["fossil_cost_bn"]["oct2026"], "fossil fuel at October 2026 prices")):
        ax.axhline(val, color=MUTED, lw=0.8, ls=(0, (3, 2)))
        ax.text(len(v) - 0.6, val + (-1.0 if "October" in lab else 0.8), lab, fontsize=6.2, color=INK2, ha="right",
                va="top" if "October" in lab else "bottom", path_effects=HALO)
    ax.set_xticks(range(len(v)), [textwrap.fill(r["step"].replace(" (= central case)", " (central case)"), 16)
                                 for r in rows], fontsize=5.8)
    ax.set_ylabel("System cost, AUD bn yr⁻¹")
    ax.set_ylim(55, 115)
    bar_ends(ax)
    save(fig, "FigS3_learning_levers")


def sfig_transition():
    T = L("transition.json")
    r = T["rows"]
    y = [x["year"] for x in r]
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.8), gridspec_kw=dict(wspace=0.35))
    ax = axs[0]
    ax.stackplot(y, [x["electric_twh"] for x in r], [x["liquid_renewable_twh"] for x in r],
                 [x["liquid_fossil_twh"] for x in r], colors=[SERIES[0], SERIES[2], "#9e9d98"],
                 labels=["Electric drive (fossil energy replaced)", "Renewable liquids and gases", "Fossil liquids"])
    ax.set_ylabel("TWh yr⁻¹")
    ax.legend(fontsize=6, loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=1)
    panel(ax, "a", "Fleet turnover and fuel build-up")
    ax = axs[1]
    ax.plot(y, [x["wtw_el_only_mt"] for x in r], color="#9e9d98", lw=2, label="Electrification only")
    ax.plot(y, [x["wtw_mt"] for x in r], color=SERIES[0], lw=2, label="Electrification + renewable fuels")
    ax.set_ylabel("Well-to-wheel Mt CO₂e yr⁻¹")
    ax.legend(fontsize=6, loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=1)
    bar_ends(ax)
    panel(ax, "b", f"{T['avoided_vs_el_only_mt']:,.0f} Mt avoided, 2025-2050")
    save(fig, "FigS4_transition")


def sfig_kelp():
    R, C = L("scenarios.json"), L("central.json")
    zt = C["kelp_zone_table"]
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    zs = sorted(zt, key=lambda z: zt[z]["aud_per_mwh_fuel"])
    ax.bar(range(len(zs)), [zt[z]["aud_per_mwh_fuel"] for z in zs], color=[SERIES[2] if C["kelp_km2"][z] >= 50 else "#b9b8b2"
                                                                         for z in zs], width=0.6)
    for i, z in enumerate(zs):
        ax.text(i, zt[z]["aud_per_mwh_fuel"] + 8, f"{zt[z]['yield_eff']:.1f} t/ha", ha="center", fontsize=6)
    ax.set_xticks(range(len(zs)), [zt[z]["name"].replace(" (", "\n(") for z in zs], rotation=40, ha="right", fontsize=5.8)
    ax.set_ylabel("Kelp fuel cost, AUD per MWh\n(farm + refinery − fertiliser)")
    bar_ends(ax)
    save(fig, "FigS5_kelp_zones")


def sfig_feed():
    F = L("feed.json")["2050"]["cross-species swap"]
    sp = ["salmon", "prawn", "barramundi", "kingfish"]
    ings = [k for k, v in F["total_t"].items() if v > 50]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    b = np.zeros(4)
    pal = SERIES + ["#9e9d98", "#3d3c39", "#c9a227", "#7fa7c6", "#b07aa1", "#5f9e6e", "#d4a6c8", "#8c6d31"]
    for i, ing in enumerate(ings):
        v = np.array([F["use_t"][ing][s] / F["feed_t"][s] * 100 for s in sp])
        ax.bar(range(4), v, bottom=b, color=pal[i % len(pal)], edgecolor="white", lw=0.8, width=0.6, label=ing)
        b += v
    ax.set_xticks(range(4), ["Salmon", "Prawns", "Barramundi", "Kingfish"])
    ax.set_ylabel("Diet inclusion, %")
    ax.legend(fontsize=5.8, loc="upper left", bbox_to_anchor=(1.0, 1.0), ncol=1)
    bar_ends(ax)
    save(fig, "FigS6_feed_composition")


def sfig_fleet_lulls():
    """Grid Harvester fleet energy and the screening lull test (moved from the main figures)."""
    CP, A = L("coproduction.json"), L("adequacy.json")
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.8), gridspec_kw=dict(wspace=0.55))
    ax = axs[0]
    gh = CP["grid_harvester"]
    ax.bar([0, 1], [gh["conventional_gwh"], gh["energy_gwh"]], color=["#9e9d98", SERIES[0]], width=0.55)
    for i, val in enumerate([gh["conventional_gwh"], gh["energy_gwh"]]):
        ax.text(i, val + 0.1, f"{val:.1f}", ha="center", fontsize=6.6, color=INK)
    ax.set_xticks([0, 1], ["Conventional\nharvester", "Grid\nHarvester"], fontsize=6.4)
    ax.set_ylabel("Harvest energy, GWh yr⁻¹")
    bar_ends(ax)
    panel(ax, "a", f"{gh['units']:.0f} Grid Harvesters, {CP['drones']['drones']:,.0f} drones")
    ax = axs[1]
    pick = [(7, 0.10, 0.10), (14, 0.05, 0.0)]
    ev = [e for k in pick for b_ in (0.6, 0.3, 0.0) for e in A["events"]
          if (e["days"], e["wind_cf"], e["hydro_share"], e["batt_credit"]) == (*k, b_)]
    xs = [0, 1, 2, 3.6, 4.6, 5.6]
    bc = {0.6: SERIES[2], 0.3: SERIES[3], 0.0: SERIES[1]}
    ax.bar(xs, [e["extra_bn"] for e in ev], color=[bc[e["batt_credit"]] for e in ev], width=0.7)
    top = max(e["extra_bn"] for e in ev) * 1.6
    for x_, e in zip(xs, ev):
        ax.text(x_, e["extra_bn"] + top * 0.03, f"{e['turbine_gw']:.0f}\nGW", ha="center", fontsize=5.8, color=INK2,
                linespacing=0.95)
    ax.set_xticks(xs, [f"{int(e['batt_credit']*100)}%" for e in ev], fontsize=6.2)
    for x_, lab in ((1, "7 days, wind 10%"), (4.6, "14 days, wind 5%,\nno hydro")):
        ax.text(x_, top * 0.97, lab, ha="center", va="top", fontsize=6.0, color=INK, linespacing=1.0)
    ax.set_xlabel("Battery power counted at the peak", fontsize=6.4, labelpad=2)
    ax.set_ylabel("Extra annual cost, AUD bn")
    ax.set_ylim(0, top)
    bar_ends(ax)
    panel(ax, "b", "Screening lull test (annual model)")
    save(fig, "FigS9_harvesters_and_screening_lulls")


def sfig_capacity_factors():
    S = json.load(open(OUT.parent / "observed_data" / "sites.json"))["sites"]
    names = list(S)
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 4.2), gridspec_kw=dict(wspace=0.08))
    for ax, tech, col in ((axs[0], "wind", SERIES[0]), (axs[1], "pv", SERIES[3])):
        y = np.arange(len(names))
        raw = [S[n][f"raw_{tech}_cf"] for n in names]
        cal = [S[n][f"{tech}_cf"] for n in names]
        lo = [min(S[n][f"{tech}_cf_by_year"].values()) for n in names]
        hi = [max(S[n][f"{tech}_cf_by_year"].values()) for n in names]
        isp = [S[n][f"isp_{tech}_cf"] for n in names]
        ax.hlines(y, lo, hi, color=col, lw=2.2, alpha=0.35)
        ax.plot(cal, y, "o", color=col, ms=3.6, label="Used (2015-2024 mean; bar: year range)")
        ax.plot(raw, y, "|", color=INK2, ms=6, label="ERA5 before scaling")
        ax.plot([v if v else np.nan for v in isp], y, "x", color=SERIES[7], ms=4, label="AEMO 2026 ISP REZ")
        ax.set_yticks(y, [n.replace("_", " ") for n in names] if tech == "wind" else [], fontsize=5.8)
        ax.invert_yaxis()
        ax.set_xlabel(f"{'Wind' if tech == 'wind' else 'Single-axis PV'} capacity factor")
        ax.grid(axis="x", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        panel(ax, "a" if tech == "wind" else "b", "Wind (140 m hub)" if tech == "wind" else "Solar PV (tracking)")
    axs[0].legend(fontsize=5.6, frameon=False, loc="lower left", bbox_to_anchor=(0, -0.25), ncol=3)
    save(fig, "FigS10_capacity_factors")


def sfig_ocean():
    O_ = json.load(open(OUT.parent / "observed_data" / "kelp_ocean.json"))
    import kelp as K
    zs = list(O_)
    lab = [K.ZONES[z].name.split(" (")[0] for z in zs]
    fig, axs = plt.subplots(1, 3, figsize=(7.2, 3.0), gridspec_kw=dict(wspace=0.15))
    y = np.arange(len(zs))
    ax = axs[0]
    ax.barh(y - 0.18, [O_[z]["mhw_days_mean_1983_2012"] for z in zs], height=0.34, color="#9e9d98", label="1983-2012")
    ax.barh(y + 0.18, [O_[z]["mhw_days_mean_2015_2024"] for z in zs], height=0.34, color=SERIES[1], label="2015-2024")
    ax.set_yticks(y, lab, fontsize=5.8)
    ax.invert_yaxis()
    ax.set_xlabel("Marine-heatwave days per year")
    ax.legend(fontsize=5.6, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
    panel(ax, "a", "Heatwaves (OISST)")
    ax = axs[1]
    ax.barh(y, [O_[z]["months_surface_no3_ge_1"] for z in zs], height=0.55, color=SERIES[2])
    ax.set_yticks(y, [])
    ax.invert_yaxis()
    ax.set_xlim(0, 12)
    ax.set_xlabel("Months with nitrate ≥1 µmol/kg, 0-30 m")
    panel(ax, "b", "Nitrate (WOA23)")
    ax = axs[2]
    ax.barh(y, [K.ZONES_PRIOR[z].area_km2 for z in zs], height=0.34, color="#9e9d98", label="Screening value")
    ax.barh(y + 0.36, [min(K.ZONES[z].area_km2, K.DEPLOYMENT_CAP_KM2) for z in zs], height=0.34, color=SERIES[0],
            label="Ocean bound, capped")
    ax.set_yticks(y, [])
    ax.invert_yaxis()
    ax.set_xlabel("Farmable area, km²")
    ax.legend(fontsize=5.6, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
    panel(ax, "c", "Area (ETOPO, 10-100 m)")
    for a_ in axs:
        a_.grid(axis="x", color=GRID, lw=0.6)
        a_.set_axisbelow(True)
    save(fig, "FigS11_kelp_ocean_data")


def sfig_fuel_costs():
    """Fig. S13: production cost by pathway, today -> 2050, per litre of diesel equivalent."""
    B = L("biofuel_costs.json")
    P = B["pathways"]
    names = sorted(P, key=lambda k: P[k]["aud_l_diesel_eq"]["2050"])
    short = lambda k: k.replace(" (air-captured CO2)", "").replace(", best zone", "").replace(" (hydrothermal liquefaction)", " (HTL)") \
        .replace(" (gasification, Fischer-Tropsch)", " (FT)").replace("Fischer-Tropsch electrofuel", "e-Fischer–Tropsch") \
        .replace(" (sorghum, cane, molasses)", "").replace(" (from biomethane)", "")
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.6), gridspec_kw=dict(width_ratios=[2.4, 1], wspace=0.06), sharey=True)
    ys = np.arange(len(names))
    for y_, k in zip(ys, names):
        a, b = P[k]["aud_l_diesel_eq"]["2026"], P[k]["aud_l_diesel_eq"]["2050"]
        ax.plot([a, b], [y_, y_], color="#b9b8b2", lw=1.6, zorder=2, solid_capstyle="round")
        ax.scatter([a], [y_], s=26, facecolor="white", edgecolor=SERIES[0], lw=1.4, zorder=3)
        ax.scatter([b], [y_], s=30, color=SERIES[0], edgecolor="white", lw=0.8, zorder=4)
        ax.text(max(a, b) + 0.24, y_, f"{b:.2f}", fontsize=5.8, va="center", color=INK2, zorder=5, bbox=dict(facecolor="white", edgecolor="none", pad=0.6))
    k = B["litre_basis_kwh"] / 1000
    for v, lab, ha, dx in ((B["fossil_pretax_aud_mwh"]["diesel_2025"] * k, "fossil diesel\n2025", "right", -0.08),
                           (B["fossil_pretax_aud_mwh"]["diesel_oct2026"] * k, "fossil diesel\nOct 2026", "left", 0.08)):
        ax.axvline(v, color=SERIES[7], lw=0.9, ls=(0, (3, 2)), zorder=1)
        ax.text(v + dx, len(names) - 0.25, lab, fontsize=5.4, color=SERIES[7], ha=ha, va="bottom", linespacing=1.0)
    ax.set_yticks(ys, [short(n) for n in names], fontsize=6.2)
    ax.set_ylim(-0.6, len(names) + 0.5)
    ax.set_xlim(0, 8.6)
    ax.set_xlabel("Production cost, AUD per litre of diesel equivalent")
    ax.scatter([], [], s=26, facecolor="white", edgecolor=SERIES[0], lw=1.4, label="Today's costs")
    ax.scatter([], [], s=30, color=SERIES[0], label="2050 learning case (value shown)")
    ax.legend(fontsize=5.8, frameon=False, loc="lower right")
    panel(ax, "a", "Cost by pathway")
    ax2.barh(ys, [P[n]["twh_2050"] for n in names], height=0.55, color="#b9b8b2")
    for y_, n in zip(ys, names):
        ax2.text(P[n]["twh_2050"] + 2, y_, f"{P[n]['twh_2050']:.0f}" if P[n]["twh_2050"] >= 1 else f"{P[n]['twh_2050']:.1f}",
                 fontsize=5.8, va="center", color=INK2)
    ax2.set_xlim(0, 125)
    ax2.set_xlabel("2050 output, TWh")
    ax2.tick_params(axis="y", length=0)
    panel(ax2, "b", "Output")
    save(fig, "FigS13_fuel_costs")


def sfig_hourly():
    D = L("dispatch.json")
    sysd = D["design"]["systems"]
    nodes = list(sysd)
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 3.0), gridspec_kw=dict(wspace=0.45))
    ax = axs[0]
    keys = [("wind_gw", "Wind", SERIES[0]), ("pv_gw", "Solar", SERIES[3]), ("battery_gw", "Battery", SERIES[2]),
            ("electrolyser_gw", "Electrolysers", SERIES[6])]
    x = np.arange(len(nodes))
    w = 0.2
    for i, (k, lab, col) in enumerate(keys):
        ax.bar(x + (i - 1.5) * w, [sysd[n][k] for n in nodes], w, color=col, label=lab)
    ax.plot(x, [L("verify_hourly.json")["turbine_gw_by_node"][n] for n in nodes], "_", color=SERIES[1], ms=14, mew=2.2,
            label="Turbines")
    ax.set_xticks(x, [n.replace("_", "/") for n in nodes], fontsize=6.4)
    ax.set_ylabel("GW")
    ax.legend(fontsize=5.6, frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.12), handlelength=1.0,
              columnspacing=0.7)
    bar_ends(ax)
    panel(ax, "a", "Final hourly fleet by grid")
    ax = axs[1]
    V = L("verify_hourly.json")["years"]
    yrs = sorted(V, key=int)
    tw = [V[y]["turbine_twh"] for y in yrs]
    cu = [sum(V[y]["curtail_twh_by_node"].values()) / 10 for y in yrs]
    ax.bar([int(y) - 0.2 for y in yrs], tw, 0.4, color=SERIES[1], label="Turbine output")
    ax.bar([int(y) + 0.2 for y in yrs], cu, 0.4, color="#b9b8b2", label="Curtailment / 10")
    for y in D["design_years"]:
        yy = max(tw[yrs.index(str(y))], cu[yrs.index(str(y))])
        ax.annotate("design\n▼", (y, yy), xytext=(0, 2), textcoords="offset points", ha="center", va="bottom",
                    fontsize=5.2, color=INK2, linespacing=0.9)
    ax.set_ylim(0, max(tw + cu) * 1.3)
    ax.set_xticks([int(y) for y in yrs], [str(y)[2:] for y in yrs], fontsize=6.2)
    ax.set_ylabel("TWh per year")
    ax.legend(fontsize=5.6, frameon=False, ncol=2, loc="upper center")
    bar_ends(ax)
    panel(ax, "b", "Final fleet fixed, each year hour by hour")
    save(fig, "FigS12_hourly_system")


def sfig_gh():
    G = L("grid_harvester.json")
    rows = G["energy"]["rows"]
    fig, ax = plt.subplots(figsize=(4.2, 2.8))
    ax.bar([f"{int(r['dry_solids_fraction']*100)}%" for r in rows], [r["grid_total_mj"] for r in rows], color=SERIES[0],
           width=0.55, label="Grid Harvester")
    ax.axhline(rows[0]["conventional_total_mj"], color=MUTED, ls=(0, (3, 2)), lw=1)
    ax.text(2.4, rows[0]["conventional_total_mj"] + 2, "conventional harvester", fontsize=6, ha="right", color=INK2)
    ax.set_xlabel("Slurry dry solids")
    ax.set_ylabel("MJ per 1.44-ha cycle")
    bar_ends(ax)
    save(fig, "FigS7_grid_harvester_energy")


def all_figures():
    sd = {"Fig1": fig1(), "Fig2": fig2(), "Fig3": fig3(), "Fig4": fig4(), "Fig5": fig6(), "FigS8": fig5()}
    sfig_fleet_lulls()
    sfig_capacity_factors()
    sfig_ocean()
    sfig_hourly()
    sfig_fuel_costs()
    sfig_illustrations()
    sfig_levers()
    sfig_transition()
    sfig_kelp()
    sfig_feed()
    sfig_gh()
    (OUT / "source_data").mkdir(exist_ok=True)
    for k, v in sd.items():
        json.dump(v, open(OUT / "source_data" / f"{k}.json", "w"), indent=1, default=float)
    return sd


if __name__ == "__main__":
    all_figures()
    print("figures written to", FIG)
