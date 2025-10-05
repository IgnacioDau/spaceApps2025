/*
 * Front‑end logic for the asteroid impact simulator.
 *
 * This script uses Three.js to render a 3D view of the solar system with
 * a simple Earth sphere and an orbit line representing an asteroid.  It
 * communicates with the Flask backend via the JSON endpoints defined in
 * app.py.  Users can input a NEO identifier or specify basic physical
 * parameters to run a simulation.  Results, including kinetic energy,
 * crater diameter and estimated seismic magnitude, are displayed in the
 * sidebar and a shareable link encodes the current settings in the query
 * string for easy sharing.
 */

let scene, camera, renderer, controls;
let earthMesh, orbitLine;
let raycaster, mouse;
let selectedDome;
const SCALE = 1 / 1000; // Convert kilometres to Three.js units
const textureLoader = new THREE.TextureLoader();

/**
 * Initialise the Three.js scene, camera and renderer.
 */
function initThree() {
    const container = document.getElementById('threeContainer');
    const width = container.clientWidth;
    const height = container.clientHeight;
    
    // Initialize scene, camera, and renderer first
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(60, width / height, 0.001, 500);
    camera.position.set(0, 0, 200);

    // Create renderer before adding event listeners
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio || 1);
    container.appendChild(renderer.domElement);

    // Add lighting
    const ambient = new THREE.AmbientLight(0x888888);
    scene.add(ambient);
    const directional = new THREE.DirectionalLight(0xffffff, 0.8);
    directional.position.set(1, 1, 1);
    scene.add(directional);

    // Create Earth with proper error handling for textures
    const earthRadiusKm = 6371;
    const geometry = new THREE.SphereGeometry(earthRadiusKm * SCALE, 64, 32);

    // Add loading manager to handle errors
    const loadManager = new THREE.LoadingManager();
    loadManager.onError = function(url) {
        console.error('Error loading texture:', url);
    };

    const textureLoader = new THREE.TextureLoader(loadManager);
    
    // Create a basic material first in case textures fail to load
    const material = new THREE.MeshPhongMaterial({
        color: 0x2233ff, // Blue color as fallback
        shininess: 10
    });

    // Create and add Earth mesh immediately with basic material
    earthMesh = new THREE.Mesh(geometry, material);
    scene.add(earthMesh);

    // Load textures and update material when ready
    Promise.all([
        new Promise(resolve => textureLoader.load('static/textures/earth_daymap.jpg', resolve)),
        new Promise(resolve => textureLoader.load('static/textures/earth_bumpmap.jpg', resolve)),
        new Promise(resolve => textureLoader.load('static/textures/earth_specular.jpg', resolve))
    ]).then(([earthTexture, bumpTexture, specularTexture]) => {
        earthMesh.material = new THREE.MeshPhongMaterial({
            map: earthTexture,
            bumpMap: bumpTexture,
            bumpScale: 0.05,
            specularMap: specularTexture,
            specular: new THREE.Color('grey'),
            shininess: 10
        });
    }).catch(error => {
        console.error('Failed to load textures:', error);
    });

    // Initialize controls after renderer is created
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.enablePan = false;
    controls.minDistance = 5;
    controls.maxDistance = 400;

    // Initialize raycaster and mouse
    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();

    // Add event listeners
    window.addEventListener('resize', onWindowResize);
    renderer.domElement.addEventListener('click', onEarthClick);

    // Start animation loop
    animate();
}

/**
 * Adjust the renderer and camera aspect ratio on window resize.
 */
function onWindowResize() {
  const container = document.getElementById('threeContainer');
  const width = container.clientWidth;
  const height = container.clientHeight;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
}

/**
 * Animation loop to render the scene.
 */
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}

function onEarthClick(event) {
    // Calculate mouse position in normalized device coordinates
    mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
    mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;

    // Update the picking ray with the camera and mouse position
    raycaster.setFromCamera(mouse, camera);

    // Calculate objects intersecting the picking ray
    const intersects = raycaster.intersectObject(earthMesh);

    if (intersects.length > 0) {
        // Remove previous dome if it exists
        if (selectedDome) {
            scene.remove(selectedDome);
        }

        // Create dome at intersection point
        const intersectionPoint = intersects[0].point;
        const domeRadius = earthMesh.geometry.parameters.radius * 0.1; // 10% of Earth radius
        const domeGeometry = new THREE.SphereGeometry(
            domeRadius, 32, 32,
            0, Math.PI * 2, 0, Math.PI / 2
        );
        const domeMaterial = new THREE.MeshPhongMaterial({
            color: 0xff0000,
            transparent: true,
            opacity: 0.5
        });

        selectedDome = new THREE.Mesh(domeGeometry, domeMaterial);
        selectedDome.position.copy(intersectionPoint);
        
        // Orient dome to face outward from Earth's center
        selectedDome.lookAt(earthMesh.position);
        selectedDome.rotateX(Math.PI / 2);
        
        scene.add(selectedDome);
    }
}

/**
 * Draw the asteroid orbit as a line in the scene.
 *
 * @param {Array} positions List of position objects with x, y and z in km.
 */
function drawOrbit(positions) {
  // Remove existing line if present
  if (orbitLine) {
    scene.remove(orbitLine);
    orbitLine.geometry.dispose();
    orbitLine.material.dispose();
    orbitLine = undefined;
  }
  // Convert positions to Vector3 points, scaling from km to scene units
  const pts = positions.map(p => new THREE.Vector3(p.x * SCALE, p.y * SCALE, p.z * SCALE));
  const geometry = new THREE.BufferGeometry().setFromPoints(pts);
  const material = new THREE.LineBasicMaterial({ color: 0xffa500 });
  orbitLine = new THREE.Line(geometry, material);
  scene.add(orbitLine);
}

/**
 * Display impact results in the sidebar as a table.
 *
 * @param {Object} impactResults Object containing kinetic energy (J), TNT equivalent (Mt), crater diameter (km) and magnitude.
 */
function displayResults(impactResults) {
  const container = document.getElementById('results');
  if (!impactResults) {
    container.innerHTML = '';
    return;
  }
  const rows = [
    { label: 'Kinetic energy', value: `${impactResults.kinetic_energy_joules.toExponential(3)} J` },
    { label: 'Energy (TNT)', value: `${impactResults.energy_megatons_tnt.toFixed(3)} Mt` },
    { label: 'Crater diameter', value: `${impactResults.crater_diameter_km.toFixed(3)} km` },
    { label: 'Seismic magnitude', value: impactResults.seismic_magnitude.toFixed(2) }
  ];
  let html = '<table class="table table-sm table-bordered">';
  for (const row of rows) {
    html += `<tr><td>${row.label}</td><td>${row.value}</td></tr>`;
  }
  html += '</table>';
  container.innerHTML = html;
}

/**
 * Construct a shareable URL containing current form values.
 */
function updateShareLink() {
  const base = window.location.origin + window.location.pathname;
  const params = new URLSearchParams();
  const neoId = document.getElementById('neoId').value.trim();
  if (neoId) params.set('neo_id', neoId);
  params.set('diameter', document.getElementById('diameter').value);
  params.set('density', document.getElementById('density').value);
  params.set('velocity', document.getElementById('velocity').value);
  params.set('angle', document.getElementById('angle').value);
  params.set('steps', document.getElementById('steps').value);
  params.set('timespan', document.getElementById('timespan').value);
  const link = base + '?' + params.toString();
  document.getElementById('shareLink').value = link;
}

/**
 * Parse query parameters on page load and prefill the form.  If any
 * parameters are present, automatically run the simulation.
 */
function parseQueryAndRun() {
  const params = new URLSearchParams(window.location.search);
  if (params.has('neo_id')) document.getElementById('neoId').value = params.get('neo_id');
  if (params.has('diameter')) document.getElementById('diameter').value = params.get('diameter');
  if (params.has('density')) document.getElementById('density').value = params.get('density');
  if (params.has('velocity')) document.getElementById('velocity').value = params.get('velocity');
  if (params.has('angle')) document.getElementById('angle').value = params.get('angle');
  if (params.has('steps')) document.getElementById('steps').value = params.get('steps');
  if (params.has('timespan')) document.getElementById('timespan').value = params.get('timespan');
  // If any query parameter is provided, run automatically
  if ([...params.keys()].length > 0) {
    runSimulation();
  }
}

/**
 * Gather user inputs and send a simulation request to the backend.
 */
async function runSimulation(event) {
  if (event) event.preventDefault();
  updateShareLink();
  const neoId = document.getElementById('neoId').value.trim();
  const payload = {};
  if (neoId) {
    payload.neo_id = neoId;
  } else {
    // Default to an Earth‑like circular orbit if no ID is supplied
    payload.orbit = {
      semi_major_axis_au: 1.0,
      eccentricity: 0.0,
      inclination_deg: 0.0,
      ascending_node_longitude_deg: 0.0,
      argument_of_periapsis_deg: 0.0,
      mean_anomaly_deg: 0.0
    };
  }
  payload.projectile_diameter_m = parseFloat(document.getElementById('diameter').value) || 0;
  payload.projectile_density = parseFloat(document.getElementById('density').value) || 0;
  payload.impact_velocity_km_s = parseFloat(document.getElementById('velocity').value) || 0;
  payload.impact_angle_deg = parseFloat(document.getElementById('angle').value) || 45;
  payload.simulation_steps = parseInt(document.getElementById('steps').value) || 200;
  payload.timespan_days = parseFloat(document.getElementById('timespan').value) || 365;
  // Send request
  try {
    const resp = await fetch('/api/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) {
      const err = await resp.json();
      alert('Simulation error: ' + (err.error || resp.statusText));
      return;
    }
    const data = await resp.json();
    drawOrbit(data.orbit_positions);
    displayResults(data.impact_results);
  } catch (err) {
    alert('Request failed: ' + err);
  }
}

// Main entry point: initialise everything when the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  initThree();
  document.getElementById('simForm').addEventListener('submit', runSimulation);
  // Update share link whenever inputs change
  const inputs = ['neoId','diameter','density','velocity','angle','steps','timespan'];
  for (const id of inputs) {
    document.getElementById(id).addEventListener('input', updateShareLink);
  }
  parseQueryAndRun();
  updateShareLink();
});