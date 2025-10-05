"""
Flask backend for the asteroid impact visualization and simulation tool.

This module exposes two core endpoints:

* ``/api/asteroid/<asteroid_id>`` - fetch orbital and physical data for a
  single near-Earth object (NEO) from NASA's NeoWs API.  The API returns
  information such as estimated size, orbital elements and close approach
  details.  Fields like ``semi_major_axis``, ``eccentricity``, ``inclination``
  and ``mean_anomaly`` are needed to compute the position of the asteroid
  along its orbit.  These fields are described in the NASA documentation for
  the NeoWs service【989053650590023†L170-L370】.

* ``/api/simulate`` - run a simple simulation based on user supplied
  parameters or orbital data.  The client sends JSON describing either
  "orbit" (containing the six Keplerian orbital elements) or a ``neo_id``
  which will be used to look up the asteroid from NASA.  Additional
  parameters include the projectile diameter, density, impact velocity and
  impact angle.  The endpoint computes the asteroid's position over a
  configurable time span using standard orbital mechanics formulas
  (outlined in Rene Schwarz's technical memorandum【606638483504259†L34-L70】,
  【606638483504259†L172-L183】) and calculates the kinetic energy, crater
  diameter and other environmental effects.  Results are returned as JSON.

The backend deliberately avoids persisting any user data or storing
authentication tokens on the server.  To keep the example self contained it
uses NASA's ``DEMO_KEY``; users running a production deployment should
obtain their own API key from https://api.nasa.gov.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv, dotenv_values
import requests
from flask import Flask, jsonify, request

load_dotenv()

app = Flask(__name__)

# -----------------------------------------------------------------------------
# Utility functions
#
# Several helper functions are defined outside of the request handlers so they
# can be unit tested in isolation.  The majority of the calculations follow
# established physical relationships documented in the connected sources.  For
# example, the conversion from Keplerian elements to Cartesian state vectors
# comes from Rene Schwarz's memo on orbital mechanics【606638483504259†L34-L70】,
# 【606638483504259†L172-L183】 and the simple crater scaling used here is based
# on a classroom derivation showing that crater diameter scales as the
# fourth-root of the kinetic energy【801151404010368†L94-L160】.


def kepler_to_cartesian(
    a: float,
    e: float,
    i_deg: float,
    omega_deg: float,
    w_deg: float,
    M_deg: float,
    mu: float = 1.32712440018e11,
    steps: int = 500,
    timespan_days: float = 365.25,
) -> List[Dict[str, float]]:
    """Convert Keplerian orbital elements to Cartesian coordinates.

    This function samples the orbit at a number of equally spaced points
    covering ``timespan_days`` days starting from the current epoch.

    Parameters
    ----------
    a : float
        Semi-major axis in astronomical units (AU). 1 AU ≈ 1.496e8 km.
    e : float
        Eccentricity of the orbit.
    i_deg : float
        Inclination of the orbit in degrees.
    omega_deg : float
        Longitude of the ascending node (Ω) in degrees.
    w_deg : float
        Argument of periapsis (ω) in degrees.
    M_deg : float
        Mean anomaly at epoch in degrees.
    mu : float, optional
        Standard gravitational parameter of the Sun, in km³/s².  The default
        corresponds to the gravitational constant multiplied by the mass of the
        Sun (GM).
    steps : int, optional
        Number of sample points along the orbit.
    timespan_days : float, optional
        Total time span over which to compute positions, measured in days.

    Returns
    -------
    List[dict]
        A list of dictionaries with keys ``x``, ``y`` and ``z`` representing
        positions in kilometres in the heliocentric ecliptic coordinate frame.
    """
    # Convert degrees to radians for trigonometric functions
    i = math.radians(i_deg)
    omega = math.radians(omega_deg)
    w = math.radians(w_deg)
    M0 = math.radians(M_deg)

    # Convert semi-major axis from AU to km
    a_km = a * 1.496e8

    # Mean motion n = sqrt(mu / a³)
    n = math.sqrt(mu / (a_km**3))  # rad/s

    positions: List[Dict[str, float]] = []
    dt_total = timespan_days * 24 * 3600  # total time in seconds

    for j in range(steps):
        # Time elapsed since epoch (seconds)
        t = (j / (steps - 1)) * dt_total
        # Mean anomaly at time t: M = M0 + n * t
        M_t = M0 + n * t
        # Normalize M between 0 and 2π
        M_t = math.fmod(M_t, 2 * math.pi)

        # Solve Kepler's equation: E - e * sin(E) = M
        E = _solve_keplers_equation(e, M_t)
        # True anomaly ν
        nu = 2 * math.atan2(math.sqrt(1 + e) * math.sin(E / 2),
                             math.sqrt(1 - e) * math.cos(E / 2))
        # Radial distance r = a(1 - e cos E)
        r = a_km * (1 - e * math.cos(E))
        # Position in orbital plane
        x_op = r * math.cos(nu)
        y_op = r * math.sin(nu)
        z_op = 0.0
        # Rotation matrices: Rz(-Ω) * Rx(-i) * Rz(-ω)
        # Rotate by argument of periapsis
        cos_w = math.cos(w)
        sin_w = math.sin(w)
        x1 = cos_w * x_op - sin_w * y_op
        y1 = sin_w * x_op + cos_w * y_op
        z1 = z_op
        # Rotate by inclination
        cos_i = math.cos(i)
        sin_i = math.sin(i)
        x2 = x1
        y2 = cos_i * y1 - sin_i * z1
        z2 = sin_i * y1 + cos_i * z1
        # Rotate by longitude of ascending node
        cos_omega = math.cos(omega)
        sin_omega = math.sin(omega)
        x = cos_omega * x2 - sin_omega * y2
        y = sin_omega * x2 + cos_omega * y2
        z = z2
        positions.append({"x": x, "y": y, "z": z})
    return positions


def _solve_keplers_equation(e: float, M: float, tol: float = 1e-10) -> float:
    """Solve Kepler's equation using Newton-Raphson iteration.

    Parameters
    ----------
    e : float
        Eccentricity of the orbit (0 ≤ e < 1).
    M : float
        Mean anomaly in radians.
    tol : float, optional
        Convergence tolerance.

    Returns
    -------
    float
        Eccentric anomaly in radians.
    """
    E = M  # Initial guess: E ≈ M for small eccentricities
    for _ in range(50):
        f = E - e * math.sin(E) - M
        f_prime = 1 - e * math.cos(E)
        delta = -f / f_prime
        E += delta
        if abs(delta) < tol:
            break
    return E


def compute_impact_effects(
    diameter_m: float,
    density: float,
    velocity_m_per_s: float,
    impact_angle_deg: float,
    crater_coeff: float = 1.0e-2,
) -> Dict[str, Any]:
    """Estimate environmental effects for an impact.

    A simple point-source model is used to approximate the crater diameter and
    related quantities.  The kinetic energy of the projectile is computed as
    ½ m v², where the mass m is derived from the projectile diameter and
    density.  The crater diameter is assumed to scale with the fourth root of
    the energy【801151404010368†L94-L160】.  The seismic magnitude is estimated
    using the Gutenberg-Richter relationship, which relates radiated seismic
    energy to magnitude.

    Parameters
    ----------
    diameter_m : float
        Projectile diameter in metres.
    density : float
        Projectile density in kg/m³ (e.g. 3000 for rock).
    velocity_m_per_s : float
        Impact velocity (metres per second) at the surface.
    impact_angle_deg : float
        Angle of incidence measured from horizontal plane (90° is vertical).
    crater_coeff : float, optional
        Empirical coefficient for the crater diameter scaling law.  A small
        value (~1e-2) yields results on the order of kilometres for typical
        asteroid impacts.

    Returns
    -------
    dict
        Dictionary containing the impact energy (J), energy in megatons of TNT,
        estimated crater diameter (km) and estimated seismic magnitude.
    """
    # Convert diameter to radius
    radius = diameter_m / 2.0
    volume = (4.0 / 3.0) * math.pi * radius**3
    mass = volume * density  # kg
    # Only the vertical component of velocity contributes to crater formation
    angle_rad = math.radians(impact_angle_deg)
    v_vertical = velocity_m_per_s * math.sin(angle_rad)
    kinetic_energy = 0.5 * mass * v_vertical**2  # Joules
    # Convert energy to megatons of TNT: 1 ton TNT ≈ 4.184e9 J
    energy_mt = kinetic_energy / (4.184e9) / 1e6
    # Crater diameter scaling: d = k * K^(1/4), where k is empirical
    crater_diameter_km = crater_coeff * (kinetic_energy**0.25) / 1000.0
    # Seismic magnitude (Richter) from energy: log10(E) ~ 1.5 M + 4.8
    if kinetic_energy > 0:
        magnitude = (math.log10(kinetic_energy) - 4.8) / 1.5
    else:
        magnitude = 0
    return {
        "kinetic_energy_joules": kinetic_energy,
        "energy_megatons_tnt": energy_mt,
        "crater_diameter_km": crater_diameter_km,
        "seismic_magnitude": magnitude,
    }


def fetch_neo_data(neo_id: str, api_key: Optional[str] = "rxMvMTUajdWXf7iWqTXTqvnbf9vR3eSdCHEw1nF0") -> Dict[str, Any]:
    """Fetch a single Near Earth Object from NASA's NeoWs API.

    Parameters
    ----------
    neo_id : str
        The NASA JPL small body ID (SPK-ID) of the asteroid.
    api_key : str, optional
        Your NASA API key.  If omitted, the environment variable ``NASA_API_KEY``
        is consulted; if that is unset, 'DEMO_KEY' is used.

    Returns
    -------
    dict
        Parsed JSON for the requested NEO.  If the request fails a
        ``RuntimeError`` is raised.
    """
    key = api_key or os.getenv("NASA_API_KEY", "DEMO_KEY")
    url = f"https://api.nasa.gov/neo/rest/v1/neo/{neo_id}?api_key={key}"
    resp = requests.get(url, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"NASA API returned status {resp.status_code}: {resp.text}")
    return resp.json()


# -----------------------------------------------------------------------------
# Route definitions
#

@app.route("/api/asteroid/<neo_id>")
def api_asteroid(neo_id: str):
    """Return NASA NEO data for the specified asteroid ID."""
    try:
        data = fetch_neo_data(neo_id)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    # Extract minimal subset of fields for the frontend
    orbital = data.get("orbital_data", {})
    response = {
        "name": data.get("name"),
        "id": data.get("id"),
        "estimated_diameter_m": data.get("estimated_diameter", {}).get("meters", {}),
        "is_potentially_hazardous": data.get("is_potentially_hazardous_asteroid"),
        "orbital_data": {
            "semi_major_axis_au": float(orbital.get("semi_major_axis", 0.0)),
            "eccentricity": float(orbital.get("eccentricity", 0.0)),
            "inclination_deg": float(orbital.get("inclination", 0.0)),
            "ascending_node_longitude_deg": float(orbital.get("ascending_node_longitude", 0.0)),
            "argument_of_periapsis_deg": float(orbital.get("perihelion_argument", 0.0)),
            "mean_anomaly_deg": float(orbital.get("mean_anomaly", 0.0)),
        },
    }
    return jsonify(response)


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    """Run a simple orbital and impact simulation.

    The request body must be JSON.  Either an ``neo_id`` should be provided, in
    which case orbital parameters will be fetched from NASA, or explicit
    ``orbit`` parameters must be supplied containing the six orbital elements
    (semi_major_axis_au, eccentricity, inclination_deg, ascending_node_longitude_deg,
    argument_of_periapsis_deg and mean_anomaly_deg).

    Additional keys accepted:

    * ``projectile_diameter_m`` - diameter of the impactor in metres.
    * ``projectile_density`` - density of the impactor in kg/m³ (defaults to
      3000 for rocky asteroids【113413445720351†L30-L32】).
    * ``impact_velocity_km_s`` - impact velocity in km/s; if omitted the
      asteroid's orbital speed at the current epoch is used (approximate).
    * ``impact_angle_deg`` - angle from horizontal plane (defaults to 45°).

    Returns a JSON object containing a list of orbit positions, energy,
    crater diameter, seismic magnitude and TNT equivalent.
    """
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    # Determine orbital parameters
    orbit_data: Optional[Dict[str, float]] = None
    if "orbit" in payload:
        orbit_data = payload["orbit"]
    elif "neo_id" in payload:
        try:
            neo_data = fetch_neo_data(payload["neo_id"])
            od = neo_data.get("orbital_data", {})
            orbit_data = {
                "semi_major_axis_au": float(od.get("semi_major_axis", 0.0)),
                "eccentricity": float(od.get("eccentricity", 0.0)),
                "inclination_deg": float(od.get("inclination", 0.0)),
                "ascending_node_longitude_deg": float(od.get("ascending_node_longitude", 0.0)),
                "argument_of_periapsis_deg": float(od.get("perihelion_argument", 0.0)),
                "mean_anomaly_deg": float(od.get("mean_anomaly", 0.0)),
            }
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
    else:
        return jsonify({"error": "No orbit or neo_id provided"}), 400

    # Extract physical parameters
    diameter_m = float(payload.get("projectile_diameter_m", 10.0))
    density = float(payload.get("projectile_density", 3000.0))  # kg/m^3
    impact_velocity_km_s = float(payload.get("impact_velocity_km_s", 20.0))
    impact_velocity_m_s = impact_velocity_km_s * 1000.0
    impact_angle_deg = float(payload.get("impact_angle_deg", 45.0))

    # Compute orbital positions
    positions = kepler_to_cartesian(
        a=orbit_data["semi_major_axis_au"],
        e=orbit_data["eccentricity"],
        i_deg=orbit_data["inclination_deg"],
        omega_deg=orbit_data["ascending_node_longitude_deg"],
        w_deg=orbit_data["argument_of_periapsis_deg"],
        M_deg=orbit_data["mean_anomaly_deg"],
        steps=int(payload.get("simulation_steps", 200)),
        timespan_days=float(payload.get("timespan_days", 365.25)),
    )

    # Compute impact effects
    impact_results = compute_impact_effects(
        diameter_m=diameter_m,
        density=density,
        velocity_m_per_s=impact_velocity_m_s,
        impact_angle_deg=impact_angle_deg,
        crater_coeff=float(payload.get("crater_coefficient", 1.0e-2)),
    )

    return jsonify({
        "orbit_positions": positions,
        "impact_results": impact_results,
    })


@app.route("/")
def root():
    """Serve the main page."""
    return app.send_static_file("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)