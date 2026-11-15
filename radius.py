#!/usr/bin/env python3
"""
Interactive Lunar Surface Resource Visualizer within radius R of (lat, lon).
Uses calibrated NASA PDS Geosciences Node datasets (Lunar Prospector LP-GRS)
registered to the 2:1 equirectangular base map (moon_color.jpg).
Displays objective concentration units (wt. %, ppm) and exports CSV.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, RadioButtons, Slider
from scipy.ndimage import map_coordinates

from generator import (
    BASE_IMAGE_PATH,
    DATA_CACHE_DIR,
    collect_resource_grids,
    discover_and_download_pds_files,
    load_base_albedo,
)

R_MOON_KM = 1737.4
CSV_OUTPUT_DIR = Path("lunar_roi_exports")

# 10 geochemical resources (objective concentration units only)
ENGLISH_RESOURCE_SPECS: list[tuple[str, str, str, str]] = [
    ("SiO2",  "Silica (SiO₂)",                        "wt. %", "YlOrRd"),
    ("O",     "Regolith-Bound Oxygen (O)",            "wt. %", "YlGn"),
    ("TiO2",  "Titanium Dioxide / Ilmenite (TiO₂)",   "wt. %", "magma"),
    ("FeO",   "Iron Oxide (FeO)",                     "wt. %", "inferno"),
    ("Th",    "Thorium – KREEP Tracer (Th)",          "ppm",   "viridis"),
    ("U",     "Uranium – KREEP Tracer (U)",           "ppm",   "plasma"),
    ("K2O",   "Potassium Oxide – KREEP (K₂O)",        "wt. %", "cividis"),
    ("Al2O3", "Aluminum Oxide / Anorthosite (Al₂O₃)", "wt. %", "GnBu"),
    ("MgO",   "Magnesium Oxide (MgO)",                "wt. %", "YlGnBu"),
    ("CaO",   "Calcium Oxide (CaO)",                  "wt. %", "PuBuGn"),
]

MAP_LAYER_KEYS = ["SiO2", "TiO2", "FeO", "Th", "U", "K2O", "Al2O3", "MgO", "CaO", "O"]

# Two separated comparison panels on the right side: Major Components [wt. %] and Trace Elements [ppm]
CHART_GROUPS = [
    (
        "Major Regolith Components [wt. %]",
        "wt. %",
        ["SiO2", "O", "Al2O3", "FeO", "CaO", "MgO", "TiO2", "K2O"],
    ),
    (
        "KREEP Trace Elements [ppm]",
        "ppm",
        ["Th", "U"],
    ),
]


class LunarDepositAnalyzer:
    """Computes area-weighted concentrations within spherical radius R."""

    def __init__(self, resources: dict[str, tuple[np.ndarray, str, int]], width: int, height: int) -> None:
        self.resources = {k: v for k, v in resources.items() if k in MAP_LAYER_KEYS}
        self.width = width
        self.height = height

        lat_1d = 90.0 - (np.arange(height) + 0.5) * (180.0 / height)
        lon_1d = -180.0 + (np.arange(width) + 0.5) * (360.0 / width)
        self.lon_grid, self.lat_grid = np.meshgrid(lon_1d, lat_1d)
        self.lat_rad_grid = np.radians(self.lat_grid)
        self.lon_rad_grid = np.radians(self.lon_grid)

        dlat_rad = np.radians(180.0 / height)
        dlon_rad = np.radians(360.0 / width)
        self.pixel_area_km2 = np.maximum(
            0.0, (R_MOON_KM ** 2) * np.cos(self.lat_rad_grid) * dlat_rad * dlon_rad
        )

        self.global_means: dict[str, float] = {}
        for key, (grid, _, _) in self.resources.items():
            valid = np.isfinite(grid)
            if np.any(valid):
                w_sum = float(np.sum(self.pixel_area_km2[valid]))
                self.global_means[key] = float(np.sum(grid[valid] * self.pixel_area_km2[valid]) / w_sum)
            else:
                self.global_means[key] = float("nan")

    def spherical_distance_km(self, lat0_deg: float, lon0_deg: float) -> np.ndarray:
        """Great-circle distance [km] on the Moon from (lat0_deg, lon0_deg) to every pixel."""
        phi1 = np.radians(lat0_deg)
        lam1 = np.radians(lon0_deg)
        dphi = self.lat_rad_grid - phi1
        dlam = self.lon_rad_grid - lam1
        a = np.sin(0.5 * dphi) ** 2 + np.cos(phi1) * np.cos(self.lat_rad_grid) * (np.sin(0.5 * dlam) ** 2)
        c = 2.0 * np.arcsin(np.minimum(1.0, np.sqrt(a)))
        return R_MOON_KM * c

    def _sample_point_bilinear(self, grid: np.ndarray, lat0_deg: float, lon0_deg: float) -> float:
        """Bilinear interpolation at (lat0, lon0) for very small query radii."""
        row = np.clip((90.0 - lat0_deg) * (self.height / 180.0) - 0.5, 0.0, self.height - 1.0)
        col = ((lon0_deg + 180.0) % 360.0) * (self.width / 360.0) - 0.5
        padded = np.pad(grid, ((0, 0), (1, 1)), mode="wrap")
        val = map_coordinates(padded, [[row], [col + 1.0]], order=1, mode="nearest")[0]
        return float(val)

    def query_roi(
        self, lat0_deg: float, lon0_deg: float, radius_km: float
    ) -> tuple[dict[str, float], list[dict[str, object]]]:
        """Computes area-weighted mean, min, and max concentrations within spherical radius R [km]."""
        dist_km = self.spherical_distance_km(lat0_deg, lon0_deg)
        mask = dist_km <= radius_km

        theta = min(np.pi, radius_km / R_MOON_KM)
        cap_area_km2 = 2.0 * np.pi * (R_MOON_KM ** 2) * (1.0 - np.cos(theta))

        meta_summary = {
            "lat_deg": round(lat0_deg, 3),
            "lon_deg": round(lon0_deg, 3),
            "radius_km": round(radius_km, 2),
            "cap_area_km2": cap_area_km2,
            "pixel_count": int(np.sum(mask)),
        }

        rows: list[dict[str, object]] = []

        for key, title, unit, _ in ENGLISH_RESOURCE_SPECS:
            if key not in self.resources:
                continue
            grid, source_label, _ = self.resources[key]

            if np.any(mask & np.isfinite(grid)):
                sub_mask = mask & np.isfinite(grid)
                vals = grid[sub_mask]
                weights = self.pixel_area_km2[sub_mask]
                w_sum = float(np.sum(weights))
                mean_val = float(np.sum(vals * weights) / w_sum) if w_sum > 0 else float(np.mean(vals))
                min_val = float(np.min(vals))
                max_val = float(np.max(vals))
            else:
                pt_val = self._sample_point_bilinear(grid, lat0_deg, lon0_deg)
                mean_val = min_val = max_val = pt_val

            glb_mean = self.global_means.get(key, float("nan"))
            diff_pct = ((mean_val - glb_mean) / abs(glb_mean) * 100.0) if (np.isfinite(glb_mean) and glb_mean != 0) else 0.0

            rows.append(
                {
                    "resource_key": key,
                    "resource_name": title,
                    "unit": unit,
                    "latitude_deg": round(lat0_deg, 3),
                    "longitude_deg": round(lon0_deg, 3),
                    "radius_km": round(radius_km, 2),
                    "surface_area_km2": round(cap_area_km2, 2),
                    "roi_weighted_mean": round(mean_val, 4),
                    "lunar_global_mean": round(glb_mean, 4),
                    "diff_vs_global_pct": round(diff_pct, 2),
                    "roi_min": round(min_val, 4),
                    "roi_max": round(max_val, 4),
                    "data_source": source_label,
                }
            )

        return meta_summary, rows


def export_rows_to_csv(rows: list[dict[str, object]], out_path: Path) -> Path:
    """Exports ROI resource concentration statistics to a UTF-8 CSV file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return out_path
    fieldnames = list(rows[0].keys())
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=",")
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def launch_interactive_visualizer(
    analyzer: LunarDepositAnalyzer,
    albedo_gray: np.ndarray,
    init_lat: float = 20.0,
    init_lon: float = -25.0,
    init_radius: float = 250.0,
) -> None:
    """Launches the interactive dashboard with sliders, comparison plots, and CSV export."""
    spec_map = {k: (title, unit, cmap) for k, title, unit, cmap in ENGLISH_RESOURCE_SPECS}
    available_layers = [k for k in MAP_LAYER_KEYS if k in analyzer.resources]
    active_layer = [available_layers[0] if available_layers else next(iter(analyzer.resources))]

    shade = 0.42 + 0.58 * albedo_gray[:, :, None]
    layer_rgb_cache: dict[str, tuple[np.ndarray, float, float]] = {}
    for k in available_layers:
        grid, _, _ = analyzer.resources[k]
        _, _, cmap_name = spec_map[k]
        vmin, vmax = np.nanpercentile(grid, [2, 98])
        if np.isclose(vmin, vmax):
            vmin, vmax = float(np.nanmin(grid)), float(np.nanmax(grid) + 1e-6)
        norm = np.clip((grid - vmin) / (vmax - vmin + 1e-9), 0.0, 1.0)
        rgba = plt.get_cmap(cmap_name)(norm)
        rgb = np.clip(rgba[:, :, :3] * shade, 0.0, 1.0)
        layer_rgb_cache[k] = (rgb, float(vmin), float(vmax))

    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "sans-serif"]
    fig = plt.figure(figsize=(16.5, 9.2), dpi=115, facecolor="#12151a")
    fig.canvas.manager.set_window_title("Lunar Surface Resource Explorer (NASA PDS Equirectangular)")

    # --- LEFT SIDE: Map + Colorbar + Sliders & Layer Selector ---
    ax_map = fig.add_axes([0.045, 0.36, 0.515, 0.56])
    ax_cbar = fig.add_axes([0.045, 0.295, 0.515, 0.018])

    ax_radio = fig.add_axes([0.045, 0.035, 0.145, 0.225], facecolor="#181c23")
    ax_s_lat = fig.add_axes([0.255, 0.215, 0.305, 0.028], facecolor="#222731")
    ax_s_lon = fig.add_axes([0.255, 0.165, 0.305, 0.028], facecolor="#222731")
    ax_s_rad = fig.add_axes([0.255, 0.115, 0.305, 0.028], facecolor="#222731")
    ax_btn_csv = fig.add_axes([0.255, 0.045, 0.146, 0.042])
    ax_btn_rst = fig.add_axes([0.414, 0.045, 0.146, 0.042])

    # --- RIGHT SIDE: 2 Separated Comparison Panels (Major Oxides [wt. %] + Trace Elements [ppm]) ---
    gs_right = fig.add_gridspec(
        2,
        1,
        left=0.625,
        right=0.982,
        top=0.920,
        bottom=0.055,
        height_ratios=[8.0, 2.6],
        hspace=0.32,
    )
    chart_axes = [fig.add_subplot(gs_right[i], facecolor="#181c23") for i in range(2)]

    # Initialize Map
    rgb0, vmin0, vmax0 = layer_rgb_cache[active_layer[0]]
    im_artist = ax_map.imshow(rgb0, extent=[-180, 180, -90, 90], origin="upper", aspect="auto")
    ax_map.set_xticks(np.arange(-180, 181, 30))
    ax_map.set_yticks(np.arange(-90, 91, 30))
    ax_map.grid(color="white", linestyle=":", linewidth=0.5, alpha=0.35)
    ax_map.tick_params(colors="#d0d7de", labelsize=8)
    ax_map.set_xlabel("Selenographic Longitude λ [°]  (click map to relocate target)", color="#c9d1d9", fontsize=8.5)
    ax_map.set_ylabel("Selenographic Latitude φ [°]", color="#c9d1d9", fontsize=8.5)

    sm = plt.cm.ScalarMappable(cmap=plt.get_cmap(spec_map[active_layer[0]][2]), norm=plt.Normalize(vmin=vmin0, vmax=vmax0))
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=ax_cbar, orientation="horizontal")
    cbar.ax.tick_params(colors="#d0d7de", labelsize=7.5)
    cbar.outline.set_edgecolor("#444c56")

    center_marker, = ax_map.plot([init_lon], [init_lat], marker="+", markersize=11, markeredgewidth=2.0, color="#00f5d4")
    roi_contour = [None]
    status_text = fig.text(0.255, 0.015, "", color="#7ee787", fontsize=8.5)

    s_lat = Slider(ax_s_lat, "Latitude φ [°]  ", -90.0, 90.0, valinit=init_lat, valstep=0.5, color="#388bfd")
    s_lon = Slider(ax_s_lon, "Longitude λ [°] ", -180.0, 180.0, valinit=init_lon, valstep=0.5, color="#388bfd")
    s_rad = Slider(ax_s_rad, "Radius R [km]   ", 10.0, 1000.0, valinit=init_radius, valstep=5.0, color="#f78166")
    for sld in (s_lat, s_lon, s_rad):
        sld.label.set_color("#e6edf3")
        sld.label.set_fontsize(8.5)
        sld.valtext.set_color("#79c0ff")
        sld.valtext.set_fontsize(8.5)

    radio = RadioButtons(ax_radio, available_layers, active=0, activecolor="#58a6ff")
    ax_radio.set_title("Map Overlay", color="#e6edf3", fontsize=8.5, pad=4)
    for lbl in radio.labels:
        lbl.set_color("#d0d7de")
        lbl.set_fontsize(7.4)

    btn_csv = Button(ax_btn_csv, "Export CSV", color="#238636", hovercolor="#2ea043")
    btn_csv.label.set_color("white")
    btn_csv.label.set_fontsize(9)
    btn_csv.label.set_fontweight("bold")

    btn_rst = Button(ax_btn_rst, "Reset (Imbrium)", color="#30363d", hovercolor="#484f58")
    btn_rst.label.set_color("#e6edf3")
    btn_rst.label.set_fontsize(8.5)

    latest_rows: list[dict[str, object]] = []

    def update_dashboard(_=None) -> None:
        nonlocal latest_rows
        lat0 = float(s_lat.val)
        lon0 = float(s_lon.val)
        rad_km = float(s_rad.val)
        layer_key = active_layer[0]

        # 1. Update map overlay
        rgb, vmin, vmax = layer_rgb_cache[layer_key]
        l_title, l_unit, l_cmap = spec_map[layer_key]
        im_artist.set_data(rgb)
        sm.set_cmap(plt.get_cmap(l_cmap))
        sm.set_clim(vmin, vmax)
        cbar.set_label(f"Active Layer: {l_title} [{l_unit}]", color="#e6edf3", fontsize=8)

        # 2. Update spherical radius R contour
        center_marker.set_data([lon0], [lat0])
        if roi_contour[0] is not None:
            try:
                roi_contour[0].remove()
            except Exception:
                for c in getattr(roi_contour[0], "collections", []):
                    c.remove()
            roi_contour[0] = None

        dist_grid = analyzer.spherical_distance_km(lat0, lon0)
        if np.nanmin(dist_grid) < rad_km < np.nanmax(dist_grid):
            roi_contour[0] = ax_map.contour(
                analyzer.lon_grid,
                analyzer.lat_grid,
                dist_grid,
                levels=[rad_km],
                colors=["#00f5d4"],
                linewidths=1.8,
            )

        # 3. Query ROI concentrations and auto-save working CSV
        meta, rows = analyzer.query_roi(lat0, lon0, rad_km)
        latest_rows = rows
        export_rows_to_csv(rows, CSV_OUTPUT_DIR / "lunar_roi_latest.csv")

        ax_map.set_title(
            f"Target: φ = {lat0:+.1f}°, λ = {lon0:+.1f}° | Radius R = {rad_km:.0f} km "
            f"(Spherical Cap Area: {meta['cap_area_km2']:,.0f} km²)",
            color="white",
            fontsize=10.2,
            fontweight="bold",
            pad=8,
        )

        # 4. Update comparison bar charts (objective units only)
        row_by_key = {r["resource_key"]: r for r in rows}

        for grp_idx, (ax, (grp_title, unit, keys)) in enumerate(zip(chart_axes, CHART_GROUPS)):
            ax.clear()
            ax.set_facecolor("#181c23")
            present_keys = [k for k in keys if k in row_by_key]
            if not present_keys:
                continue

            roi_vals = [float(row_by_key[k]["roi_weighted_mean"]) for k in present_keys]
            glb_vals = [float(row_by_key[k]["lunar_global_mean"]) for k in present_keys]
            rel_pcts = [float(row_by_key[k]["diff_vs_global_pct"]) for k in present_keys]

            y_pos = np.arange(len(present_keys))
            ax.barh(y_pos - 0.18, roi_vals, height=0.34, color="#58a6ff", label=f"ROI R={rad_km:.0f} km")
            ax.barh(y_pos + 0.18, glb_vals, height=0.34, color="#6e7681", label="Global Mean")

            ax.set_yticks(y_pos)
            ax.set_yticklabels(present_keys, color="#e6edf3", fontsize=8.5, fontweight="bold")
            ax.invert_yaxis()

            hi_val = max(max(roi_vals), max(glb_vals), 1e-6)
            ax.set_xlim(0.0, hi_val * 1.48)

            ax.grid(axis="x", color="#30363d", linestyle="--", linewidth=0.6)
            ax.tick_params(colors="#c9d1d9", labelsize=7.5)
            ax.set_title(grp_title, color="white", fontsize=9.5, fontweight="bold", loc="left", pad=5)

            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            for spine in ("bottom", "left"):
                ax.spines[spine].set_color("#30363d")

            for i, (rv, gv, rel) in enumerate(zip(roi_vals, glb_vals, rel_pcts)):
                x_txt = max(rv, gv) + 0.02 * hi_val
                ax.text(
                    x_txt,
                    i,
                    f"{rv:.2f} {unit} ({rel:+.0f}%)",
                    va="center",
                    ha="left",
                    color="#d0d7de",
                    fontsize=7.6,
                )

            if grp_idx == 0:
                ax.legend(
                    loc="lower right",
                    fontsize=7.8,
                    facecolor="#21262d",
                    edgecolor="#30363d",
                    labelcolor="#e6edf3",
                )

        fig.canvas.draw_idle()

    def on_layer_change(label: str) -> None:
        active_layer[0] = label
        update_dashboard()

    def on_map_click(event) -> None:
        if event.inaxes != ax_map or event.xdata is None or event.ydata is None:
            return
        new_lon = float(np.clip(event.xdata, -180.0, 180.0))
        new_lat = float(np.clip(event.ydata, -90.0, 90.0))
        s_lat.eventson = False
        s_lon.eventson = False
        s_lat.set_val(round(new_lat * 2.0) / 2.0)
        s_lon.set_val(round(new_lon * 2.0) / 2.0)
        s_lat.eventson = True
        s_lon.eventson = True
        update_dashboard()

    def on_export_csv(_event) -> None:
        lat0, lon0, rad_km = float(s_lat.val), float(s_lon.val), float(s_rad.val)
        fname = f"lunar_roi_lat{lat0:+.1f}_lon{lon0:+.1f}_R{rad_km:.0f}km.csv"
        saved = export_rows_to_csv(latest_rows, CSV_OUTPUT_DIR / fname)
        status_text.set_text(f"Exported CSV: {saved}")
        print(f"[CSV] Exported report: {saved}")
        fig.canvas.draw_idle()

    def on_reset(_event) -> None:
        s_lat.eventson = False
        s_lon.eventson = False
        s_rad.eventson = False
        s_lat.set_val(20.0)
        s_lon.set_val(-25.0)
        s_rad.set_val(250.0)
        s_lat.eventson = True
        s_lon.eventson = True
        s_rad.eventson = True
        update_dashboard()

    s_lat.on_changed(update_dashboard)
    s_lon.on_changed(update_dashboard)
    s_rad.on_changed(update_dashboard)
    radio.on_clicked(on_layer_change)
    btn_csv.on_clicked(on_export_csv)
    btn_rst.on_clicked(on_reset)
    fig.canvas.mpl_connect("button_press_event", on_map_click)

    update_dashboard()
    plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(description="Lunar Surface Resource Analyzer within radius R.")
    parser.add_argument("--lat", type=float, default=20.0, help="Selenographic latitude [-90..90]")
    parser.add_argument("--lon", type=float, default=-25.0, help="Selenographic longitude [-180..180]")
    parser.add_argument("--radius", type=float, default=250.0, help="Search radius R [km]")
    parser.add_argument("--csv", type=str, default=None, help="Direct output CSV file path")
    parser.add_argument("--no-gui", action="store_true", help="Compute and export CSV without opening GUI")
    args = parser.parse_args()

    albedo_gray, width, height = load_base_albedo(BASE_IMAGE_PATH)
    discover_and_download_pds_files(DATA_CACHE_DIR)
    resources = collect_resource_grids(DATA_CACHE_DIR, albedo_gray)

    analyzer = LunarDepositAnalyzer(resources, width, height)

    if args.csv or args.no_gui:
        meta, rows = analyzer.query_roi(args.lat, args.lon, args.radius)
        out_csv = (
            Path(args.csv)
            if args.csv
            else CSV_OUTPUT_DIR / f"lunar_roi_lat{args.lat:+.1f}_lon{args.lon:+.1f}_R{args.radius:.0f}km.csv"
        )
        export_rows_to_csv(rows, out_csv)
        print(
            f"[OK] ROI: lat={meta['lat_deg']}°, lon={meta['lon_deg']}°, R={meta['radius_km']} km "
            f"| Surface Area={meta['cap_area_km2']:,.1f} km²"
        )
        print(f"[CSV] Saved report to: {out_csv}")
        if args.no_gui:
            return

    launch_interactive_visualizer(
        analyzer=analyzer,
        albedo_gray=albedo_gray,
        init_lat=args.lat,
        init_lon=args.lon,
        init_radius=args.radius,
    )


if __name__ == "__main__":
    main()
