// mapbox-gl-draw hardcodes "mapboxgl-*" class names; MapLibre uses "maplibregl-*".
// Point the constants at MapLibre's classes so controls render/position correctly.
MapboxDraw.constants.classes.CANVAS = 'maplibregl-canvas'
MapboxDraw.constants.classes.CONTROL_BASE = 'maplibregl-ctrl'
MapboxDraw.constants.classes.CONTROL_PREFIX = 'maplibregl-ctrl-'
MapboxDraw.constants.classes.CONTROL_GROUP = 'maplibregl-ctrl-group'
MapboxDraw.constants.classes.ATTRIBUTION = 'maplibregl-ctrl-attrib'

const map = new maplibregl.Map({
  container: 'map',
  style: 'https://tiles.openfreemap.org/styles/liberty',
  center: [0, 20],
  zoom: 2,
  pitch: 0,
  bearing: 0,
  minZoom: 0,
  maxZoom: 22,
  antialias: true
})

map.addControl(new maplibregl.NavigationControl(), 'top-right')

const panelEl = document.getElementById('panel')
document.getElementById('panel-toggle').addEventListener('click', () => {
  const collapsed = panelEl.classList.toggle('collapsed')
  document.getElementById('panel-toggle').title = collapsed ? 'Expand panel' : 'Minimize panel'
})

// Default draw styles reference sprite icons (e.g. "vertex-stroke-blue") that
// don't exist in the openfreemap style's sprite, which breaks rendering/hit-testing.
// Use plain circle/line/fill layers instead, per MapLibre's mapbox-gl-draw example.
// Palette matches the panel: iOS blue while actively drawing/editing, iOS green once a
// shape is finished, with a soft glow line underneath for a less "CAD tool" look.
const ACCENT = '#0a84ff'
const DONE = '#30d158'

const drawStyles = [
  // soft glow sitting under the finished-polygon outline
  { id: 'gl-draw-polygon-glow-inactive', type: 'line', filter: ['all', ['==', 'active', 'false'], ['==', '$type', 'Polygon'], ['!=', 'mode', 'static']], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': DONE, 'line-width': 9, 'line-opacity': 0.18, 'line-blur': 3 } },
  { id: 'gl-draw-polygon-fill-inactive', type: 'fill', filter: ['all', ['==', 'active', 'false'], ['==', '$type', 'Polygon'], ['!=', 'mode', 'static']], paint: { 'fill-color': DONE, 'fill-opacity': 0.1 } },
  { id: 'gl-draw-polygon-fill-active', type: 'fill', filter: ['all', ['==', 'active', 'true'], ['==', '$type', 'Polygon']], paint: { 'fill-color': ACCENT, 'fill-opacity': 0.12 } },
  { id: 'gl-draw-polygon-midpoint', type: 'circle', filter: ['all', ['==', '$type', 'Point'], ['==', 'meta', 'midpoint']], paint: { 'circle-radius': 4, 'circle-color': '#fff', 'circle-stroke-color': ACCENT, 'circle-stroke-width': 1.5, 'circle-opacity': 0.9 } },
  { id: 'gl-draw-polygon-stroke-inactive', type: 'line', filter: ['all', ['==', 'active', 'false'], ['==', '$type', 'Polygon'], ['!=', 'mode', 'static']], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': DONE, 'line-width': 2.5 } },
  { id: 'gl-draw-polygon-stroke-active', type: 'line', filter: ['all', ['==', 'active', 'true'], ['==', '$type', 'Polygon']], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': ACCENT, 'line-dasharray': [0.3, 1.6], 'line-width': 2.5 } },
  { id: 'gl-draw-line-inactive', type: 'line', filter: ['all', ['==', 'active', 'false'], ['==', '$type', 'LineString'], ['!=', 'mode', 'static']], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': DONE, 'line-width': 2.5 } },
  { id: 'gl-draw-line-active', type: 'line', filter: ['all', ['==', '$type', 'LineString'], ['==', 'active', 'true']], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': ACCENT, 'line-dasharray': [0.3, 1.6], 'line-width': 2.5 } },
  { id: 'gl-draw-polygon-and-line-vertex-inactive', type: 'circle', filter: ['all', ['==', 'meta', 'vertex'], ['==', '$type', 'Point'], ['!=', 'mode', 'static']], paint: { 'circle-radius': 5.5, 'circle-color': '#fff', 'circle-stroke-color': ACCENT, 'circle-stroke-width': 2.5 } },
  { id: 'gl-draw-point-point-stroke-inactive', type: 'circle', filter: ['all', ['==', 'active', 'false'], ['==', '$type', 'Point'], ['==', 'meta', 'feature'], ['!=', 'mode', 'static']], paint: { 'circle-radius': 6, 'circle-color': '#fff', 'circle-stroke-color': DONE, 'circle-stroke-width': 2.5 } },
  { id: 'gl-draw-point-stroke-active', type: 'circle', filter: ['all', ['==', '$type', 'Point'], ['==', 'active', 'true'], ['!=', 'meta', 'midpoint']], paint: { 'circle-radius': 7, 'circle-color': '#fff', 'circle-stroke-color': ACCENT, 'circle-stroke-width': 3 } },
  { id: 'gl-draw-polygon-fill-static', type: 'fill', filter: ['all', ['==', 'mode', 'static'], ['==', '$type', 'Polygon']], paint: { 'fill-color': '#8e8e93', 'fill-opacity': 0.1 } },
  { id: 'gl-draw-polygon-stroke-static', type: 'line', filter: ['all', ['==', 'mode', 'static'], ['==', '$type', 'Polygon']], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#8e8e93', 'line-width': 2 } },
  { id: 'gl-draw-line-static', type: 'line', filter: ['all', ['==', 'mode', 'static'], ['==', '$type', 'LineString']], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#8e8e93', 'line-width': 2 } },
  { id: 'gl-draw-point-static', type: 'circle', filter: ['all', ['==', 'mode', 'static'], ['==', '$type', 'Point']], paint: { 'circle-radius': 5, 'circle-color': '#8e8e93' } }
]

const draw = new MapboxDraw({
  displayControlsDefault: false,
  controls: { polygon: true, trash: true },
  styles: drawStyles
})
map.addControl(draw, 'top-left')

function renderVertices(ring) {
  let html = '<ol class="vertex-list">'
  ring.forEach(([lng, lat], i) => {
    if (i === ring.length - 1 && i > 0) return // skip closing duplicate of first point
    html += `<li>lat: ${lat.toFixed(6)}, lng: ${lng.toFixed(6)}</li>`
  })
  return html + '</ol>'
}

async function fetchNamesForPolygon(ring) {
  // ring is [lng, lat] pairs (GeoJSON order); API wants [lat, lng]
  const points = ring.map(([lng, lat]) => [lat, lng])
  const res = await fetch('/api/lookup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ points })
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Lookup failed')
  return data
}

// draw.create/update/delete can fire again before a previous updateCoordsPanel()
// run has finished fetching. Each run stamps itself with a generation number so
// a stale run's late-arriving fetch result never overwrites DOM the next run
// already rebuilt (which otherwise left polygon blocks stuck on "Looking up..."
// forever, with the real result silently dropped).
let renderGeneration = 0

async function updateCoordsPanel() {
  const myGeneration = ++renderGeneration
  const data = draw.getAll()
  const panel = document.getElementById('coords-panel')

  if (!data.features.length) {
    panel.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" fill="none" class="empty-icon"><path d="M4 7l6-3 6 3 4-2v12l-4 2-6-3-6 3V7Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
        <p>Draw a polygon to see its lat/lng vertices,<br/>streets, and nearby places here.</p>
      </div>`
    return
  }

  let html = ''
  for (let fi = 0; fi < data.features.length; fi++) {
    const feature = data.features[fi]
    if (feature.geometry.type !== 'Polygon') continue

    const ring = feature.geometry.coordinates[0] // [lng, lat] pairs
    const areaM2 = turf.area(feature)
    const areaLabel = areaM2 < 10000
      ? `${areaM2.toFixed(1)} m²`
      : `${(areaM2 / 1e6).toFixed(3)} km²`

    html += `<div class="polygon-block" data-fi="${fi}">`
    html += `<h4>Polygon ${fi + 1}</h4>`
    html += `<p class="area">Area: ${areaLabel}</p>`
    html += renderVertices(ring)
    html += `<div class="loading-row"><span class="spinner"></span>Looking up streets & places...</div>`
    html += `</div>`
  }
  if (myGeneration !== renderGeneration) return // superseded before we even rendered
  panel.innerHTML = html

  // fetch every polygon's names in parallel; each patches its own block the
  // moment it resolves, instead of blocking on earlier polygons first.
  data.features.forEach((feature, fi) => {
    if (feature.geometry.type !== 'Polygon') return
    const ring = feature.geometry.coordinates[0]

    fetchNamesForPolygon(ring).then(result => {
      if (myGeneration !== renderGeneration) return // a newer draw event took over
      const block = panel.querySelector(`.polygon-block[data-fi="${fi}"]`)
      const loading = block && block.querySelector('.loading-row')
      if (!loading) return

      let namesHtml = `<p class="section-label">🛣️ Streets (${result.streets.length})</p>`
      namesHtml += '<ul class="name-list">' + (result.streets.map(s => `<li>${s}</li>`).join('') || '<li>None found</li>') + '</ul>'
      namesHtml += `<p class="section-label">🍽️ Restaurants & shops (${result.places.length})</p>`
      namesHtml += '<ul class="name-list">' + (result.places.map(p => `<li>${p.name} <span class="category">${p.category}</span></li>`).join('') || '<li>None found</li>') + '</ul>'

      loading.outerHTML = namesHtml
    }).catch(e => {
      if (myGeneration !== renderGeneration) return
      const block = panel.querySelector(`.polygon-block[data-fi="${fi}"]`)
      const loading = block && block.querySelector('.loading-row')
      if (loading) loading.outerHTML = `<p class="error-text">Lookup error: ${e.message}</p>`
    })
  })
}

map.on('draw.create', updateCoordsPanel)
map.on('draw.update', updateCoordsPanel)
map.on('draw.delete', updateCoordsPanel)

map.on('load', () => {
  map.addSource('terrain-dem', {
    type: 'raster-dem',
    tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
    tileSize: 256,
    encoding: 'terrarium',
    maxzoom: 15
  })

  map.addLayer({
    id: 'sky',
    type: 'sky',
    paint: {
      'sky-type': 'atmosphere',
      'sky-atmosphere-sun-intensity': 15
    }
  })

  map.setLight({ anchor: 'viewport', color: 'white', intensity: 0.35 })

  map.addSource('live-devices', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
  map.addLayer({
    id: 'live-devices-layer',
    type: 'circle',
    source: 'live-devices',
    layout: { visibility: 'none' },
    paint: {
      'circle-radius': 5,
      'circle-color': ['match', ['get', 'movement_mode'],
        'driving', '#ff453a',
        'walking', '#0a84ff',
        'stationary', '#8e8e93',
        '#8e8e93'
      ],
      'circle-stroke-width': 1.5,
      'circle-stroke-color': '#fff',
      'circle-opacity': 0.9
    }
  })

  map.addSource('crowd-risk', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
  map.addLayer({
    id: 'crowd-risk-fill',
    type: 'fill',
    source: 'crowd-risk',
    layout: { visibility: 'none' },
    paint: {
      'fill-color': ['match', ['get', 'reason'],
        'panic_outward', '#ff453a',
        'crush_inward', '#ffd60a',
        '#ffd60a'
      ],
      'fill-opacity': 0.22
    }
  })
  map.addLayer({
    id: 'crowd-risk-outline',
    type: 'line',
    source: 'crowd-risk',
    layout: { visibility: 'none' },
    paint: {
      'line-color': ['match', ['get', 'reason'],
        'panic_outward', '#ff453a',
        'crush_inward', '#ffd60a',
        '#ffd60a'
      ],
      'line-width': 2,
      'line-dasharray': [0.2, 1.4]
    }
  })

  // Tight danger-zone marker drawn from the actual flagged devices (hotspot),
  // not the whole multi-km detector grid cell -- only crowd-risk-fill/outline
  // above are used as a fallback when a flag has no hotspot (e.g. variance_spike).
  // px-per-km conversion is a visual approximation (not true Web Mercator math),
  // tuned to look right across normal zoom levels for a city-scale demo.
  // NOTE: a zoom expression (['zoom']) is only legal as the OUTERMOST expression
  // of a paint property -- it cannot be nested inside '*'. So the per-km-at-this-zoom
  // scale factor has to be baked into each interpolation stop's own value expression.
  function radiusExpr(mult) {
    return ['interpolate', ['linear'], ['zoom'],
      10, ['*', ['get', 'radius_km'], 7 * mult],
      14, ['*', ['get', 'radius_km'], 30 * mult],
      16, ['*', ['get', 'radius_km'], 90 * mult],
      18, ['*', ['get', 'radius_km'], 260 * mult]
    ]
  }
  map.addSource('crowd-risk-hotspot', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
  // Simple flat marker: one uniform light-red fill over the whole zone (clamped
  // to the actual incident radius, e.g. 2km) plus a solid matching outline ring
  // so the boundary stays readable against the basemap at any zoom.
  map.addLayer({
    id: 'crowd-risk-hotspot-fill',
    type: 'circle',
    source: 'crowd-risk-hotspot',
    layout: { visibility: 'none' },
    paint: {
      'circle-radius': radiusExpr(1.0),
      'circle-color': ['match', ['get', 'reason'], 'panic_outward', '#f87171', 'crush_inward', '#fde047', '#facc15'],
      'circle-opacity': 0.4
    }
  })
  map.addLayer({
    id: 'crowd-risk-hotspot-ring',
    type: 'circle',
    source: 'crowd-risk-hotspot',
    layout: { visibility: 'none' },
    paint: {
      'circle-radius': radiusExpr(1.0),
      'circle-color': 'rgba(0,0,0,0)',
      'circle-stroke-width': 2.5,
      'circle-stroke-color': ['match', ['get', 'reason'], 'panic_outward', '#b91c1c', 'crush_inward', '#ca8a04', '#a16207'],
      'circle-stroke-opacity': 0.9
    }
  })
})

// ---------- Live simulated device positions ----------
function devicesToGeoJSON(devices) {
  return {
    type: 'FeatureCollection',
    features: devices.map(d => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [d.longitude, d.latitude] },
      properties: { subscriber_id: d.subscriber_id, movement_mode: d.movement_mode, speed_kmh: d.speed_kmh }
    }))
  }
}

const liveStatusEl = document.getElementById('live-status')
let livePollTimer = null
let liveOn = false
let hasFlownToLive = false

let latestDevices = []

async function pollLivePositions() {
  try {
    const res = await fetch('/api/live-positions')
    const data = await res.json()
    if (!res.ok) {
      liveStatusEl.textContent = data.error || 'Simulator not running - start live_position_simulator.py'
      return
    }
    latestDevices = data.devices
    const src = map.getSource('live-devices')
    if (src) src.setData(devicesToGeoJSON(data.devices))
    liveStatusEl.textContent = `${data.devices.length} live devices · updated ${new Date(data.generated_at).toLocaleTimeString()}`

    if (!hasFlownToLive && data.devices.length) {
      hasFlownToLive = true
      const lats = data.devices.map(d => d.latitude)
      const lngs = data.devices.map(d => d.longitude)
      map.flyTo({
        center: [(Math.min(...lngs) + Math.max(...lngs)) / 2, (Math.min(...lats) + Math.max(...lats)) / 2],
        zoom: 12,
        duration: 1500
      })
    }
  } catch (e) {
    liveStatusEl.textContent = 'Could not reach /api/live-positions'
  }
}

const livePopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 })

map.on('mouseenter', 'live-devices-layer', () => {
  map.getCanvas().style.cursor = 'pointer'
})
map.on('mouseleave', 'live-devices-layer', () => {
  map.getCanvas().style.cursor = ''
  livePopup.remove()
})
map.on('mousemove', 'live-devices-layer', (e) => {
  const f = e.features[0]
  const p = f.properties
  const [lng, lat] = f.geometry.coordinates
  livePopup
    .setLngLat([lng, lat])
    .setHTML(
      `<strong>${p.subscriber_id}</strong><br/>` +
      `Mode: ${p.movement_mode}<br/>` +
      `Speed: ${p.speed_kmh} km/h<br/>` +
      `Lat/Lng: ${lat.toFixed(5)}, ${lng.toFixed(5)}`
    )
    .addTo(map)
})

function boundsToPolygon(b) {
  return [[
    [b.lon_min, b.lat_min], [b.lon_max, b.lat_min],
    [b.lon_max, b.lat_max], [b.lon_min, b.lat_max],
    [b.lon_min, b.lat_min]
  ]]
}

let flewToHotspotKey = null

async function pollCrowdRisk() {
  try {
    const res = await fetch('/api/crowd-risk')
    const data = await res.json()
    const cellSrc = map.getSource('crowd-risk')
    const hotspotSrc = map.getSource('crowd-risk-hotspot')
    if (!cellSrc || !hotspotSrc) return
    const flags = data.flags || []

    // flags with a hotspot (panic_outward/crush_inward) get a tight glowing circle
    // on the actual incident; flags without one (variance_spike) fall back to the
    // full detector-cell rectangle so nothing silently disappears.
    const withHotspot = flags.filter(f => f.hotspot)
    const withoutHotspot = flags.filter(f => !f.hotspot)

    if (withHotspot.length && !flewToHotspotKey) {
      const f = withHotspot[0]
      flewToHotspotKey = `${f.hotspot.lat},${f.hotspot.lon}`
      map.flyTo({ center: [f.hotspot.lon, f.hotspot.lat], zoom: Math.max(map.getZoom(), 15), duration: 1800 })
    } else if (!withHotspot.length) {
      flewToHotspotKey = null
    }

    hotspotSrc.setData({
      type: 'FeatureCollection',
      features: withHotspot.map(flag => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [flag.hotspot.lon, flag.hotspot.lat] },
        properties: { reason: flag.reason, detail: flag.detail, device_count: flag.device_count, radius_km: Math.min(flag.hotspot.radius_km, 2) }
      }))
    })
    cellSrc.setData({
      type: 'FeatureCollection',
      features: withoutHotspot.map(flag => ({
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: boundsToPolygon(flag.bounds) },
        properties: { reason: flag.reason, detail: flag.detail, device_count: flag.device_count }
      }))
    })

    updateCitizenPanel(withHotspot[0] || null)
  } catch (e) {
    // crowd_anomaly_agent.py not running yet - leave whatever was last drawn
  }
}

document.getElementById('toggle-live').addEventListener('click', () => {
  liveOn = !liveOn
  document.getElementById('toggle-live').classList.toggle('active', liveOn)
  liveStatusEl.style.display = liveOn ? 'block' : 'none'
  for (const id of ['live-devices-layer', 'crowd-risk-fill', 'crowd-risk-outline', 'crowd-risk-hotspot-fill', 'crowd-risk-hotspot-ring']) {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', liveOn ? 'visible' : 'none')
  }
  if (liveOn) {
    pollLivePositions()
    pollCrowdRisk()
    livePollTimer = setInterval(() => { pollLivePositions(); pollCrowdRisk() }, 1500)
  } else {
    clearInterval(livePollTimer)
    document.getElementById('citizen-panel').classList.remove('active')
  }
})

// ---------- Citizen.AI emergency response console (mockup) ----------
// Everything below renders real, already-measured data (live device positions,
// the detector's own hotspot geometry) -- only the action buttons are mocked;
// no actual call/SMS/Twitter integration exists.
const REASON_LABELS = {
  panic_outward: 'Mass Panic Detected',
  crush_inward: 'Protest / Mass Gathering Detected',
  variance_spike: 'Movement Anomaly'
}

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371
  const toRad = d => d * Math.PI / 180
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(a))
}

let citizenActiveFlag = null
let citizenVendorKey = null
let citizenVendors = []

function circlePolygon(lat, lon, radiusKm, n = 16) {
  const pts = []
  for (let i = 0; i < n; i++) {
    const a = (i / n) * 2 * Math.PI
    const dLat = (radiusKm / 111.32) * Math.cos(a)
    const dLon = (radiusKm / (111.32 * Math.cos(lat * Math.PI / 180) + 1e-9)) * Math.sin(a)
    pts.push([lat + dLat, lon + dLon])
  }
  return pts
}

async function fetchNearbyVendors(lat, lon, radiusKm) {
  try {
    const res = await fetch('/api/lookup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points: circlePolygon(lat, lon, radiusKm) })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || 'lookup failed')
    citizenVendors = data.places || []
  } catch (e) {
    citizenVendors = []
  }
}

function updateCitizenPanel(flag) {
  const panel = document.getElementById('citizen-panel')
  citizenActiveFlag = flag

  if (!flag) {
    panel.classList.remove('active')
    citizenVendorKey = null
    return
  }
  panel.classList.add('active')

  const label = REASON_LABELS[flag.reason] || flag.reason
  const dot = flag.reason === 'crush_inward' ? '🟡' : '🔴'
  document.getElementById('citizen-incident').innerHTML = `
    <p class="ci-title">${dot} ${label}</p>
    <p class="ci-meta">${flag.detail}<br/>
    Epicenter: ${flag.hotspot.lat.toFixed(5)}, ${flag.hotspot.lon.toFixed(5)} · zone radius ${Math.min(flag.hotspot.radius_km, 2).toFixed(1)} km</p>
  `

  const zoneKm = Math.min(flag.hotspot.radius_km, 2)
  const nearby = latestDevices
    .map(d => ({ id: d.subscriber_id, dist: haversineKm(flag.hotspot.lat, flag.hotspot.lon, d.latitude, d.longitude) }))
    .filter(d => d.dist <= zoneKm)
    .sort((a, b) => a.dist - b.dist)
    .slice(0, 12)

  const listEl = document.getElementById('citizen-sub-list')
  listEl.innerHTML = nearby.length
    ? nearby.map(d => `<li><span class="sub-id">${d.id}</span><span class="sub-dist">${(d.dist * 1000).toFixed(0)} m</span></li>`).join('')
    : '<li class="sub-empty">No subscribers resolved in zone yet</li>'

  // vendor lookup shells out to python/osmium -- only re-run it when the epicenter
  // actually changes, not on every 1.5s poll tick.
  const vendorKey = `${flag.hotspot.lat.toFixed(4)},${flag.hotspot.lon.toFixed(4)}`
  if (vendorKey !== citizenVendorKey) {
    citizenVendorKey = vendorKey
    fetchNearbyVendors(flag.hotspot.lat, flag.hotspot.lon, zoneKm)
  }

  pollCrowdIntel(flag)
}

// crowd-monitoring-agent's own debounce key format, so this matches whatever
// incident its poller.js is actually working on for the same flag.
function hunterKeyFor(flag) {
  return flag.cell ? `${flag.reason}:cell[${flag.cell[0]},${flag.cell[1]}]` : null
}

function timeAgo(isoString) {
  const diffMs = Date.now() - new Date(isoString).getTime()
  const mins = Math.max(0, Math.round(diffMs / 60000))
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m`
  return `${Math.round(mins / 60)}h`
}

function renderTweetCard(t) {
  return `
    <div class="tweet-card">
      <div class="tweet-head">
        <span class="tweet-handle">${t.handle}</span>
        <span class="tweet-time">${timeAgo(t.timestamp)}</span>
      </div>
      <p class="tweet-text">${t.text}</p>
      <div class="tweet-meta"><span>♥ ${t.likes}</span><span>⟲ ${t.retweets}</span></div>
    </div>
  `
}

async function pollCrowdIntel(flag) {
  const section = document.getElementById('citizen-hunter-section')
  const body = document.getElementById('citizen-hunter-body')
  const key = hunterKeyFor(flag)
  if (!key) { section.style.display = 'none'; return }

  try {
    const res = await fetch('/api/crowd-intel')
    const data = await res.json()
    const incident = (data.incidents || []).find(i => i.key === key)

    if (!incident) {
      section.style.display = 'block'
      body.innerHTML = '<p class="hunter-loading"><span class="spinner"></span>Gathering live posts…</p>'
      return
    }

    const tweets = incident.tweets || []
    section.style.display = 'block'
    body.innerHTML = tweets.length
      ? `<div class="tweet-feed">${tweets.map(renderTweetCard).join('')}</div>`
      : '<p class="hunter-loading"><span class="spinner"></span>Gathering live posts…</p>'

    renderNearbyRestaurants(incident.context?.vendors?.vendors || [])
  } catch (e) {
    section.style.display = 'block'
    body.innerHTML = `<p class="hunter-loading">Could not reach /api/crowd-intel</p>`
  }
}

function renderNearbyRestaurants(vendors) {
  const section = document.getElementById('nearby-restaurants-section')
  const list = document.getElementById('nearby-restaurants-list')
  if (!section || !list) return

  const food = vendors.filter(v => v.category && v.category.startsWith('amenity:'))
  const shown = (food.length ? food : vendors).slice(0, 15)

  if (!shown.length) {
    section.style.display = 'none'
    return
  }
  section.style.display = 'block'
  list.innerHTML = shown.map(v => `
    <li>
      <span class="restaurant-name">${v.name}</span>
      <span class="restaurant-category">${(v.category || '').replace(/^(shop|amenity):/, '')}</span>
    </li>
  `).join('')
}

function showCitizenToast(msg, ms = 2600) {
  const el = document.getElementById('citizen-toast')
  el.textContent = msg
  el.classList.add('show')
  clearTimeout(showCitizenToast._t)
  showCitizenToast._t = setTimeout(() => el.classList.remove('show'), ms)
}

document.getElementById('btn-call-emergency').addEventListener('click', () => {
  showCitizenToast('📞 Connecting to Frankfurt Emergency Dispatch (112)…')
})

document.querySelectorAll('.citizen-service-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    showCitizenToast(`🚨 ${btn.dataset.service} services alerted for current zone`)
  })
})

document.getElementById('btn-spread-alert').addEventListener('click', () => {
  const n = 500 + Math.floor(Math.random() * 4500)
  showCitizenToast(`📢 Automated alert tweeted · reaching ~${n.toLocaleString()} nearby followers`)
})

document.getElementById('btn-send-message').addEventListener('click', () => {
  const count = citizenActiveFlag ? citizenActiveFlag.device_count : 0
  showCitizenToast(`✉️ Mass alert SMS sent to ${count} subscribers in the zone`)
})

document.getElementById('btn-email-vendors').addEventListener('click', () => {
  if (!citizenVendors.length) {
    showCitizenToast('📧 No vendors found in this zone to email')
    return
  }
  showCitizenToast(`📧 Advisory email sent to ${citizenVendors.length} nearby shops/restaurants`)
})

let is3D = false
document.getElementById('toggle-3d').addEventListener('click', () => {
  is3D = !is3D
  map.easeTo({ pitch: is3D ? 60 : 0, bearing: is3D ? -17 : 0, duration: 800 })
  document.getElementById('toggle-3d').classList.toggle('active', is3D)
})

let terrainOn = false
document.getElementById('toggle-terrain').addEventListener('click', () => {
  terrainOn = !terrainOn
  map.setTerrain(terrainOn ? { source: 'terrain-dem', exaggeration: 1.3 } : null)
  document.getElementById('toggle-terrain').classList.toggle('active', terrainOn)
})

// ---------- City search ----------
let cityList = []
const searchInput = document.getElementById('city-search')
const searchBox = searchInput.closest('.search-box')
const cityResultsEl = document.getElementById('city-results')
const clearBtn = document.getElementById('city-search-clear')

fetch('/api/regions')
  .then(r => r.json())
  .then(list => { cityList = list })
  .catch(() => { cityList = [] })

function renderCityResults(query) {
  const q = query.trim().toLowerCase()
  const matches = q ? cityList.filter(c => c.name.toLowerCase().includes(q)) : cityList

  if (!matches.length) {
    cityResultsEl.innerHTML = '<li class="no-match">No downloaded city matches</li>'
  } else {
    cityResultsEl.innerHTML = matches.map(c =>
      `<li data-lat="${c.center.lat}" data-lng="${c.center.lng}" data-zoom="${c.zoom}">
        <span class="city-name">${c.name}</span>
        <span class="city-hint">fly to →</span>
      </li>`
    ).join('')
  }
  cityResultsEl.classList.add('open')
}

searchInput.addEventListener('focus', () => renderCityResults(searchInput.value))
searchInput.addEventListener('input', () => {
  searchBox.classList.toggle('has-text', searchInput.value.length > 0)
  renderCityResults(searchInput.value)
})

cityResultsEl.addEventListener('mousedown', (e) => {
  const li = e.target.closest('li[data-lat]')
  if (!li) return
  const lat = parseFloat(li.dataset.lat)
  const lng = parseFloat(li.dataset.lng)
  const zoom = parseFloat(li.dataset.zoom)
  searchInput.value = li.querySelector('.city-name').textContent
  searchBox.classList.add('has-text')
  cityResultsEl.classList.remove('open')
  map.flyTo({ center: [lng, lat], zoom, duration: 2000 })
})

clearBtn.addEventListener('click', () => {
  searchInput.value = ''
  searchBox.classList.remove('has-text')
  renderCityResults('')
  searchInput.focus()
})

document.addEventListener('click', (e) => {
  if (!e.target.closest('.search-box') && !e.target.closest('.city-results')) {
    cityResultsEl.classList.remove('open')
  }
})

document.getElementById('fly-demo').addEventListener('click', () => {
  is3D = true
  document.getElementById('toggle-3d').classList.add('active')
  map.flyTo({
    center: [-73.9857, 40.7484],
    zoom: 16,
    pitch: 60,
    bearing: -20,
    duration: 3000
  })
})
