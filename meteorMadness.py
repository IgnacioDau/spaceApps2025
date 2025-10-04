import requests, math

API_KEY = 'rxMvMTUajdWXf7iWqTXTqvnbf9vR3eSdCHEw1nF0'
BASE_URL = 'https://api.nasa.gov/neo/rest/v1/neo'

def fetch_asteroid_data(asteroid_id):
    asteroid_id = asteroid_id.strip()
    for candidate in (asteroid_id,):
        url = f"{BASE_URL}/{candidate}"
        resp = requests.get(url, params={"api_key": API_KEY})
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            print(f"404: '{candidate}' not found.")
        else:
            print(f"Error {resp.status_code}: {resp.text}")
    # fallback: try using browse fields if user pasted a browse object accidentally
    print("Tip: use the 'id' from the browse endpoint for lookups.")
    return None

def calculate_mass_kgs(d_min_km, d_max_km, density_kgm3=2000):
    """Compute mass (kg) from diameter range (km) and density (kg/m^3)."""
    # Average diameter in km, convert to radius in meters
    avg_d_km = (d_min_km + d_max_km) / 2
    radius_m = (avg_d_km * 1000) / 2
    volume = (4/3) * math.pi * radius_m**3
    return density_kgm3 * volume

def print_asteroid_info(data):
    """Print key asteroid info and calculated mass."""
    name = data.get('name', 'N/A')
    # NeoWs uses 'neo_reference_id' for the ID
    astro_id = data.get('neo_reference_id') or data.get('id', 'N/A')
    abs_mag = data.get('absolute_magnitude_h', 'N/A')
    diam = data.get('estimated_diameter', {}).get('kilometers', {})
    d_min = diam.get('estimated_diameter_min')
    d_max = diam.get('estimated_diameter_max')
    
    if d_min is None or d_max is None:
        print("Diameter data not available.")
        return

    mass_kg = calculate_mass_kgs(d_min, d_max)
    hazard = data.get('is_potentially_hazardous_asteroid', False)
    jpl_url = data.get('nasa_jpl_url', 'N/A')

    print(f"Name: {name}")
    print(f"ID: {astro_id}")
    print(f"Absolute magnitude (H): {abs_mag}")
    print(f"Estimated diameter: {d_min:.3f} km – {d_max:.3f} km")
    print(f"Assumed density: 2000 kg/m^3 (typical) ")
    print(f"Estimated mass: {mass_kg:.3e} kg")
    print(f"Potentially hazardous: {hazard}")
    print(f"JPL URL: {jpl_url}")

def browse_catalog():
    """Interactively browse asteroid names/IDs using the NeoWs 'browse' endpoint."""
    page = 0
    while True:
        resp = requests.get(f"{BASE_URL}/browse", params={'api_key': API_KEY, 'page': page})
        if resp.status_code != 200:
            print("Error fetching catalog page.")
            return None
        data = resp.json()
        neos = data.get('near_earth_objects', [])
        if not neos:
            print("No asteroids found.")
            return None

        print(f"\n=== Asteroid Catalog (page {page}) ===")
        for idx, obj in enumerate(neos, start=1):
            print(f"{idx}. {obj['name']}  (ID: {obj['neo_reference_id']})")
        cmd = input("Enter number to select, 'n' for next page, 'p' for previous, or 'q' to quit: ").strip().lower()
        if cmd.isdigit():
            sel = int(cmd)
            if 1 <= sel <= len(neos):
                return neos[sel-1]['neo_reference_id']
        elif cmd in ('n', 'next'):
            page += 1
        elif cmd in ('p', 'prev') and page > 0:
            page -= 1
        elif cmd in ('q', 'quit'):
            return None

# Main interactive loop
while True:
    choice = input("\nEnter an asteroid ID, 'list' to browse catalog, or 'exit': ").strip().lower()
    if choice in ('exit', 'quit'):
        break
    if choice == 'list':
        selected_id = browse_catalog()
        if not selected_id:
            continue
        data = fetch_asteroid_data(selected_id)
    else:
        data = fetch_asteroid_data(choice)

    if data:
        print("\n--- Asteroid Information ---")
        print_asteroid_info(data)




J_PER_GRAM_TNT = 4184.0

def kinetic_energy(m, v):
    return 0.5 * m * v * v

def tnt_equivalents(energy_j):
    return energy_j / J_PER_GRAM_TNT / 1_000_000 #Value in tons of TNT