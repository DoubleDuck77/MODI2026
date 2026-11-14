// Obserwator na powierzchni Księżyca (współrzędne selenograficzne).

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export class ObserverState extends EventTarget {
  lat_deg = 0;
  lon_deg = 0;

  set(lat, lon) {
    const nextLat = clamp(Number(lat), -90, 90);
    const nextLon = clamp(Number(lon), -180, 180);
    if (!Number.isFinite(nextLat) || !Number.isFinite(nextLon)) return;
    if (nextLat === this.lat_deg && nextLon === this.lon_deg) return;
    this.lat_deg = nextLat;
    this.lon_deg = nextLon;
    this.dispatchEvent(new Event('observerchange'));
  }
}
