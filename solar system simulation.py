
import numpy as np
import matplotlib.pyplot as plt

from scipy.integrate import solve_ivp
from astroquery.jplhorizons import Horizons
from astropy.time import Time
import astropy.units as u


# ============================================================
# 1. STAŁE FIZYCZNE
# ============================================================

G = 6.67430e-11             # stała grawitacji [m^3/(kg s^2)]
AU = 149597870700.0         # jednostka astronomiczna [m]
DAY = 86400.0               # doba [s]

# Stała grawitacji w jednostkach AU^3 / (kg day^2)
G = G * DAY**2 / AU**3


# ============================================================
# 2. DANE CIAŁ NIEBIESKICH
# ============================================================

# Nazwa : (identyfikator JPL, masa [kg])

bodies = {
    "Słońce":    ("10",  1.98847e30),
    "Merkury":   ("199", 3.3011e23),
    "Wenus":     ("299", 4.8675e24),
    "Ziemia":    ("399", 5.97237e24),
    "Księżyc":   ("301", 7.342e22),
    "Mars":      ("499", 6.4171e23),
    "Jowisz":    ("599", 1.8982e27),
    "Saturn":    ("699", 5.6834e26),
    "Uran":      ("799", 8.6810e25),
    "Neptun":    ("899", 1.02413e26)
}

names = list(bodies.keys())

masses = np.array([
    bodies[name][1] for name in names
])

n = len(names)


# ============================================================
# 3. POBIERANIE RZECZYWISTYCH WARUNKÓW POCZĄTKOWYCH
# ============================================================

# Dokładna epoka początkowa
epoch_utc = Time(
    "2000-01-01 00:00:00",
    scale="utc"
)

# JPL Horizons wykorzystuje czas TDB
epoch_tdb = epoch_utc.tdb

# Barycentryczny układ odniesienia
epoch_jd = epoch_tdb.jd

# Tablice położeń i prędkości
r0 = np.zeros((n, 3))
v0 = np.zeros((n, 3))

print("Pobieranie efemeryd JPL Horizons...")

for i, name in enumerate(names):

    object_id = bodies[name][0]

    obj = Horizons(
        id=object_id,
        location="@0",
        epochs=epoch_jd
    )

    vectors = obj.vectors(
        refplane="ecliptic"
    )

    # Położenie [AU]
    r0[i] = [
        vectors["x"][0],
        vectors["y"][0],
        vectors["z"][0]
    ]

    # Prędkość [AU/day]
    v0[i] = [
        vectors["vx"][0],
        vectors["vy"][0],
        vectors["vz"][0]
    ]

    print(f"Pobrano: {name}")


# ============================================================
# 4. RÓWNANIA RUCHU PROBLEMU N CIAŁ
# ============================================================

# Parametry grawitacyjne poszczególnych ciał
mu = G * masses


def equations(t, y):

    # Rozdzielenie wektora stanu
    r = y[:3*n].reshape((n, 3))
    v = y[3*n:].reshape((n, 3))

    # Różnice położeń:
    # diff[i,j] = r[j] - r[i]
    diff = r[np.newaxis, :, :] - r[:, np.newaxis, :]

    # Odległości między wszystkimi parami ciał
    distances = np.linalg.norm(diff, axis=2)

    # Wyzerowanie oddziaływania ciała na samo siebie
    np.fill_diagonal(distances, np.inf)

    # Przyspieszenia grawitacyjne
    acceleration = np.sum(
        mu[np.newaxis, :, np.newaxis]
        * diff / distances[:, :, np.newaxis]**3,
        axis=1
    )

    # Pochodna wektora stanu
    dydt = np.concatenate([
        v.flatten(),
        acceleration.flatten()
    ])

    return dydt


# ============================================================
# 5. WARUNKI POCZĄTKOWE
# ============================================================

y0 = np.concatenate([
    r0.flatten(),
    v0.flatten()
])


# ============================================================
# 6. CAŁKOWANIE RÓWNAŃ RUCHU
# ============================================================

# Epoka końcowa
end_utc = Time(
    "2100-01-01 00:00:00",
    scale="utc"
)

end_tdb = end_utc.tdb

# Czas symulacji w dobach TDB
T = (end_tdb - epoch_tdb).to_value(u.day)

# Zapis wyników co 2 dni
output_step = 2.0

t_eval = np.arange(
    0,
    T,
    output_step
)

t_eval = np.append(t_eval, T)

print("\nRozpoczynam całkowanie...")

solution = solve_ivp(
    equations,
    (0, T),
    y0,
    method="DOP853",
    t_eval=t_eval,
    rtol=2e-11,
    atol=1e-13,
    max_step=0.5
)

if not solution.success:
    raise RuntimeError(solution.message)

print("Symulacja zakończona!")


# ============================================================
# 7. ODCZYT TRAJEKTORII
# ============================================================

# Kształt: (liczba_ciał, liczba_chwil, 3)
positions = solution.y[:3*n].reshape(
    n, 3, -1
).transpose(0, 2, 1)


# ============================================================
# 8. PRZEJŚCIE DO UKŁADU HELIOCENTRYCZNEGO
# ============================================================

# Położenia względem Słońca
sun_index = names.index("Słońce")

heliocentric_positions = (
    positions - positions[sun_index][np.newaxis, :, :]
)


# ============================================================
# 9. WYKRES 3D
# ============================================================

fig = plt.figure(figsize=(14, 12))

ax = fig.add_subplot(
    111,
    projection="3d"
)

for i, name in enumerate(names):

    trajectory = heliocentric_positions[i]

    # Słońce zaznaczamy w początku układu
    if name == "Słońce":
        continue

    ax.plot(
        trajectory[:, 0],
        trajectory[:, 1],
        trajectory[:, 2],
        label=name
    )

    # Położenie początkowe
    ax.scatter(
        trajectory[0, 0],
        trajectory[0, 1],
        trajectory[0, 2],
        s=12
    )


# Słońce
ax.scatter(
    0, 0, 0,
    color="orange",
    s=100,
    label="Słońce"
)

ax.set_title(
    "Trajektorie ciał Układu Słonecznego (2000–2100)",
    fontsize=14
)

ax.set_xlabel("X [AU]")
ax.set_ylabel("Y [AU]")
ax.set_zlabel("Z [AU]")

ax.legend()

# Jednakowa skala osi
all_positions = heliocentric_positions.reshape(-1, 3)

max_range = np.max(np.abs(all_positions))

ax.set_xlim(-max_range, max_range)
ax.set_ylim(-max_range, max_range)
ax.set_zlim(-max_range, max_range)

ax.set_box_aspect((1, 1, 1))

plt.tight_layout()
plt.show()
