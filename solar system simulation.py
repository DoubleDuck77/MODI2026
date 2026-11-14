
import numpy as np
import matplotlib.pyplot as plt
from numba import njit


# ============================================================
# 1. STAŁE FIZYCZNE
# ============================================================

G_SI = 6.67430e-11
AU = 149597870700.0
DAY = 86400.0

G = G_SI * DAY**2 / AU**3


# ============================================================
# 2. PARAMETRY SYMULACJI
# ============================================================

START_YEAR = 2000
END_YEAR = 2100

T = 36525.0       # czas symulacji [dni]
DT = 0.1          # krok całkowania [dni]

SAVE_EVERY = 20   # zapis co 2 dni

N_STEPS = int(round(T / DT))


# ============================================================
# 3. CIAŁA NIEBIESKIE I ICH MASY
# ============================================================

names = [
    "Sun",
    "Mercury",
    "Venus",
    "Earth",
    "Moon",
    "Mars",
    "Jupiter",
    "Saturn",
    "Uranus",
    "Neptune"
]

masses = np.array([
    1.98847e30,
    3.3011e23,
    4.8675e24,
    5.97237e24,
    7.342e22,
    6.4171e23,
    1.8982e27,
    5.6834e26,
    8.6810e25,
    1.02413e26
], dtype=np.float64)

N = len(masses)


# ============================================================
# 4. WARUNKI POCZĄTKOWE
# ============================================================

# Położenia heliocentryczne [AU]
# Prędkości heliocentryczne [AU/day]

initial_conditions = np.array([

    # Sun
    [0, 0, 0, 0, 0, 0],

    # Mercury
    [-0.119619860, -0.368152075, 0,
     0.026295648, -0.008543974, 0],

    # Venus
    [-0.723221833, -0.012623884, 0,
     0.000353000, -0.020223346, 0],

    # Earth
    [-0.181549040, 0.983381892, 0,
     -0.016916488, -0.003123072, 0],

    # Moon
    [-0.178979040, 0.983381892, 0,
     -0.016916488, -0.002533072, 0],

    # Mars
    [1.517880941, -0.132797375, 0,
     0.001214611, 0.013883069, 0],

    # Jupiter
    [4.314643143, 2.910263547, 0,
     -0.004216619, 0.006251394, 0],

    # Saturn
    [6.159576549, 7.340697481, 0,
     -0.004256967, 0.003572020, 0],

    # Uranus
    [13.350222427, -13.824560019, 0,
     0.002822692, 0.002725842, 0],

    # Neptune
    [16.837298324, -24.962321310, 0,
     0.002599003, 0.001753050, 0]

], dtype=np.float64)


r0 = initial_conditions[:, :3].copy()
v0 = initial_conditions[:, 3:].copy()


# ============================================================
# 5. PRZEJŚCIE DO UKŁADU BARYCENTRYCZNEGO
# ============================================================

total_mass = np.sum(masses)

r_cm = np.sum(
    masses[:, np.newaxis] * r0,
    axis=0
) / total_mass

v_cm = np.sum(
    masses[:, np.newaxis] * v0,
    axis=0
) / total_mass

r0 -= r_cm
v0 -= v_cm


# ============================================================
# 6. OBLICZANIE PRZYSPIESZEŃ GRAWITACYJNYCH
# ============================================================

@njit
def calculate_acceleration(r, masses):

    n = len(masses)

    a = np.zeros((n, 3))

    for i in range(n):

        for j in range(n):

            if i == j:
                continue

            dx = r[j, 0] - r[i, 0]
            dy = r[j, 1] - r[i, 1]
            dz = r[j, 2] - r[i, 2]

            distance_squared = (
                dx*dx + dy*dy + dz*dz
            )

            distance = np.sqrt(distance_squared)

            factor = (
                G * masses[j] /
                (distance_squared * distance)
            )

            a[i, 0] += factor * dx
            a[i, 1] += factor * dy
            a[i, 2] += factor * dz

    return a


# ============================================================
# 7. INTEGRATOR VELOCITY VERLET (KDK)
# ============================================================

@njit
def simulate(r0, v0, masses, dt, n_steps, save_every):

    n = len(masses)

    max_saved = n_steps // save_every + 2

    positions = np.empty(
        (max_saved, n, 3),
        dtype=np.float64
    )

    times = np.empty(max_saved)

    r = r0.copy()
    v = v0.copy()

    a = calculate_acceleration(r, masses)

    saved = 0

    positions[saved] = r
    times[saved] = 0.0
    saved += 1

    for step in range(1, n_steps + 1):

        # KICK
        v_half = v + 0.5 * dt * a

        # DRIFT
        r += dt * v_half

        # Nowe przyspieszenie
        a_new = calculate_acceleration(r, masses)

        # KICK
        v = v_half + 0.5 * dt * a_new

        a = a_new

        if step % save_every == 0 or step == n_steps:

            positions[saved] = r
            times[saved] = step * dt

            saved += 1

    return positions[:saved], times[:saved]


# ============================================================
# 8. URUCHOMIENIE SYMULACJI
# ============================================================

print("Rozpoczynam symulację...")
print("Liczba ciał:", N)
print("Krok czasowy:", DT, "dni")
print("Liczba kroków:", N_STEPS)

positions, times = simulate(
    r0,
    v0,
    masses,
    DT,
    N_STEPS,
    SAVE_EVERY
)

print("Symulacja zakończona!")


# ============================================================
# 9. UKŁAD HELIOCENTRYCZNY
# ============================================================

sun_positions = positions[:, 0, :]

heliocentric_positions = (
    positions - sun_positions[:, np.newaxis, :]
)


# ============================================================
# 10. ZAPIS WYNIKÓW
# ============================================================

np.savez_compressed(
    "solar_system_2000_2100.npz",
    times=times,
    positions=positions,
    heliocentric_positions=heliocentric_positions,
    names=np.array(names),
    masses=masses
)

print("Zapisano wyniki symulacji.")


# ============================================================
# 11. WYKRES 3D - CAŁY UKŁAD SŁONECZNY
# ============================================================

fig = plt.figure(figsize=(14, 12))

ax = fig.add_subplot(111, projection="3d")

for i, name in enumerate(names):

    if name == "Sun":
        continue

    trajectory = heliocentric_positions[:, i, :]

    ax.plot(
        trajectory[:, 0],
        trajectory[:, 1],
        trajectory[:, 2],
        label=name,
        linewidth=0.8
    )

ax.scatter(
    0, 0, 0,
    color="orange",
    s=100,
    label="Sun"
)

ax.set_title(
    "Solar System: 2000-2100",
    fontsize=15
)

ax.set_xlabel("X [AU]")
ax.set_ylabel("Y [AU]")
ax.set_zlabel("Z [AU]")

ax.legend()

max_range = np.max(np.abs(heliocentric_positions))

ax.set_xlim(-max_range, max_range)
ax.set_ylim(-max_range, max_range)
ax.set_zlim(-max_range, max_range)

ax.set_box_aspect((1, 1, 1))

plt.tight_layout()
plt.savefig("solar_system_3D.png", dpi=300)
plt.show()


# ============================================================
# 12. WYKRES 3D - PLANETY WEWNĘTRZNE
# ============================================================

fig = plt.figure(figsize=(12, 10))

ax = fig.add_subplot(111, projection="3d")

inner_planets = [
    "Mercury",
    "Venus",
    "Earth",
    "Moon",
    "Mars"
]

for name in inner_planets:

    i = names.index(name)

    trajectory = heliocentric_positions[:, i, :]

    ax.plot(
        trajectory[:, 0],
        trajectory[:, 1],
        trajectory[:, 2],
        label=name,
        linewidth=0.8
    )

ax.scatter(
    0, 0, 0,
    color="orange",
    s=100,
    label="Sun"
)

ax.set_xlim(-2, 2)
ax.set_ylim(-2, 2)
ax.set_zlim(-2, 2)

ax.set_box_aspect((1, 1, 1))

ax.set_xlabel("X [AU]")
ax.set_ylabel("Y [AU]")
ax.set_zlabel("Z [AU]")

ax.set_title("Inner Solar System: 2000-2100")

ax.legend()

plt.tight_layout()
plt.savefig("inner_solar_system_3D.png", dpi=300)
plt.show()
