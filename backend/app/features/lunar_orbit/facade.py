"""Fasada ``lunar_orbit``: cienki adapter na ``neworb.py`` (tylko import, bez zmian w fizyce).

Propagacja jest bezstanowa: klient podaje stan i dostaje kolejną paczkę próbek. Jedna podpaczka
(``sample_dt_s``) odpowiada jednej klatce pętli pygame (``neworb.py:1296-1320``): kroki RK4
≤ ``MAX_STEP``, wektory Ziemi i Słońca interpolowane liniowo w obrębie podpaczki, a przy
wyłączonych perturbacjach — wektory zerowe.
"""

import logging
import math
import threading
import time

import numpy as np

from app.core.contracts import CONTRACT_VERSION, ReferenceFrame, ResponseMeta
from app.core.facade import BaseFacade
from app.core.legacy import import_root_script
from app.features.lunar_orbit.contract import (
    CustomOrbitDefaults,
    Landmark,
    Mascon,
    OrbitCatalog,
    OrbitInitialQuery,
    OrbitPreset,
    OrbitPresetId,
    OrbitPropagateQuery,
    OrbitState,
    OrbitTrack,
)

log = logging.getLogger(__name__)

# Etykiety przycisków presetów — kolejność i teksty z ``neworb.py:1127-1133``.
PRESET_LABELS = (
    ("LRO", "LRO"),
    ("Gateway NRHO", "Gateway"),
    ("Luna 10", "Luna 10"),
    ("Apollo PFS-2", "Apollo PFS-2"),
    ("Custom", "CUSTOM"),
)

# Komunikaty końca symulacji — dosłownie z ``neworb.py:1298-1320``.
STATUS_MESSAGES = {
    "crash": "Crashed into the lunar surface",
    "escape": "Probe left the simulation region",
    "nan": "Numerical error: state is not finite",
    "ephemeris_end": "End of ephemeris data (2100-01-01 00:00 UTC)",
}

# Nazwy punktów orientacyjnych z ``neworb.LUNAR_LANDMARKS`` wysyłane na stronę po angielsku.
LANDMARK_NAMES_EN = {"Biegun N": "North Pole", "Biegun S": "South Pole"}

UNITS = {"distance": "km", "velocity": "km/s", "time": "s", "angle": "deg", "gravity_anomaly": "mGal"}


def _vec(v) -> tuple:
    return (float(v[0]), float(v[1]), float(v[2]))


class LunarOrbitFacade(BaseFacade):
    feature_id = "lunar_orbit"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.nb = import_root_script("neworb", ctx.settings.scripts_dir)
        self.eph = self.nb.Ephemeris(ctx.settings.coords_dir)
        threading.Thread(target=self._warm_up_jit, name="neworb-jit-warmup", daemon=True).start()

    # --- pomocnicze ----------------------------------------------------------------------

    def _meta(self, endpoint: str) -> ResponseMeta:
        return ResponseMeta(
            feature=self.feature_id, endpoint=endpoint, contract_version=CONTRACT_VERSION,
            source="computed", frame=ReferenceFrame.MOON_BODY_FIXED, units=UNITS,
        )

    def _ephem_seconds(self, t) -> float:
        return float(self.nb.to_ephem_seconds(t.replace(tzinfo=None)))

    def _warm_up_jit(self) -> None:
        """Kompiluje ``@njit`` z neworb w tle, żeby pierwsze żądanie nie czekało na JIT."""
        nb = self.nb
        t0 = time.perf_counter()
        try:
            pos, vel = nb.get_preset_orbit("LRO")
            state = np.concatenate([pos, vel]).astype(np.float64)
            last = np.array([pos[0], pos[1], pos[2], 0.0])
            buf = np.empty((2, 4))
            z = np.zeros(3)
            nb.propagate(state, 0.0, 1, 1.0, True, False, z, z, z, z, last, buf)  # bez 3. ciała: zerowe wektory
            nb.mascon_diagnostics(state[:3])
            log.info("neworb JIT gotowy w %.1f s", time.perf_counter() - t0)
        except Exception:  # pragma: no cover - tylko log, endpointy zgłoszą błąd same
            log.exception("rozgrzewka JIT neworb nie powiodła się")

    # --- endpointy -----------------------------------------------------------------------

    def catalog(self) -> OrbitCatalog:
        nb = self.nb
        return OrbitCatalog(
            meta=self._meta("catalog"),
            r_moon_km=nb.R_MOON,
            gm_moon_km3_s2=nb.GM_MOON,
            omega_moon_rad_s=nb.OMEGA_MOON,
            r_escape_km=nb.R_ESCAPE,
            max_step_s=nb.MAX_STEP,
            presets=[OrbitPreset(id=OrbitPresetId(pid), label=label) for label, pid in PRESET_LABELS],
            custom_defaults=CustomOrbitDefaults(
                altitude_km=100.0, inclination_deg=45.0, speed_kms=float(nb.circular_speed(100.0))
            ),
            mascons=[
                Mascon(name=n, lat_deg=la, lon_deg=lo, depth_km=d, core_radius_km=b, delta_mu_km3_s2=mu)
                for n, la, lo, d, b, mu in nb.LUNAR_MASCONS
            ],
            landmarks=[
                Landmark(name=LANDMARK_NAMES_EN.get(n, n), lat_deg=la, lon_deg=lo, kind=k, color_rgb=tuple(nb.LANDMARK_COLORS[k]))
                for n, la, lo, k in nb.LUNAR_LANDMARKS
            ],
        )

    def initial(self, q: OrbitInitialQuery) -> OrbitState:
        nb = self.nb
        if q.preset == OrbitPresetId.CUSTOM:
            speed = q.speed_kms if q.speed_kms is not None else nb.circular_speed(q.altitude_km)
            pos, vel = nb.orbital_state(q.altitude_km, q.inclination_deg, speed)
        else:
            pos, vel = nb.get_preset_orbit(q.preset.value, self.eph, self._ephem_seconds(q.t))
        return OrbitState(meta=self._meta("initial"), t=q.t, preset=q.preset, pos_km=_vec(pos), vel_kms=_vec(vel))

    def propagate(self, q: OrbitPropagateQuery) -> OrbitTrack:
        nb, eph = self.nb, self.eph
        t0 = self._ephem_seconds(q.t)
        end = min(t0 + q.duration_s, eph.t_max)
        truncated = end < t0 + q.duration_s

        state = np.array([q.x_km, q.y_km, q.z_km, q.vx_kms, q.vy_kms, q.vz_kms], dtype=np.float64)
        last = np.array([q.x_km, q.y_km, q.z_km, t0], dtype=np.float64)
        buf = np.empty((math.ceil(q.sample_dt_s / nb.MAX_STEP) + 1, 4), dtype=np.float64)
        zero3 = np.zeros(3)

        cols = {k: [] for k in OrbitTrack.model_fields if k not in
                ("meta", "t", "use_mascons", "third_body", "status", "status_message")}

        def record(t: float, earth, sun) -> None:
            pos, vel = state[:3], state[3:]
            hp, ha, ecc, inc = nb.osculating_elements(pos, vel)
            dg_r, dg_h, nearest = nb.mascon_diagnostics(pos)
            cols["t_offset_s"].append(t - t0)
            cols["pos_km"].append(_vec(pos))
            cols["vel_kms"].append(_vec(vel))
            cols["sun_body_km"].append(_vec(sun))
            cols["earth_body_km"].append(_vec(earth))
            cols["altitude_km"].append(float(np.linalg.norm(pos) - nb.R_MOON))
            cols["speed_kms"].append(float(np.linalg.norm(nb.inertial_velocity(pos, vel))))
            cols["periapsis_km"].append(float(hp))
            cols["apoapsis_km"].append(float(ha) if math.isfinite(ha) else None)
            cols["eccentricity"].append(float(ecc))
            cols["inclination_deg"].append(float(inc))
            cols["mascon_dg_radial_mgal"].append(float(dg_r))
            cols["mascon_dg_horiz_mgal"].append(float(dg_h))
            cols["nearest_mascon"].append(nearest)

        t = t0
        earth0, sun0 = nb.moon_frame_vectors(eph, min(t, eph.t_max))
        record(t, earth0, sun0)
        status = "ok"
        while t < end - 1e-9:
            dt = min(q.sample_dt_s, end - t)
            n = max(1, math.ceil(dt / nb.MAX_STEP))
            earth1, sun1 = nb.moon_frame_vectors(eph, t + dt)
            if q.third_body:
                e0, e1, s0, s1 = earth0, earth1, sun0, sun1
            else:
                e0 = e1 = s0 = s1 = zero3
            code, t, _ = nb.propagate(state, float(t), int(n), float(dt / n), bool(q.use_mascons),
                                      bool(q.third_body), e0, e1, s0, s1, last, buf)
            if code == nb.STATUS_NAN:
                status = "nan"  # stan nieskończony — nie zapisujemy go (JSON nie zna NaN/inf)
                break
            record(t, earth1, sun1)
            earth0, sun0 = earth1, sun1
            if code == nb.STATUS_CRASH:
                status = "crash"
                break
            if code == nb.STATUS_ESCAPE:
                status = "escape"
                break
        if status == "ok" and truncated:
            status = "ephemeris_end"

        return OrbitTrack(
            meta=self._meta("propagate"),
            t=q.t,
            use_mascons=q.use_mascons,
            third_body=q.third_body,
            status=status,
            status_message=STATUS_MESSAGES.get(status),
            **cols,
        )
