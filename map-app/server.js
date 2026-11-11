const express = require('express')
const path = require('path')
const fs = require('fs')
const { execFile } = require('child_process')

const app = express()
const PORT = process.env.PORT || 3000

const OSM_DIR = path.join(__dirname, '..', 'osm-extract')
const REGIONS = JSON.parse(fs.readFileSync(path.join(OSM_DIR, 'regions.json'), 'utf8'))
const LIVE_POSITIONS_PATH = path.join(__dirname, '..', 'simulation', 'live_positions.json')
const CROWD_RISK_PATH = path.join(__dirname, '..', 'social-media-sentiment-agent', 'crowd_risk.json')
const CROWD_INTEL_PATH = path.join(__dirname, '..', 'crowd-monitoring-agent', 'crowd_monitoring_output.json')

app.use(express.static(path.join(__dirname, 'public')))
app.use(express.json())

function findRegionForPolygon(points) {
  // points: [[lat, lng], ...]. Use the centroid to pick which city's .pbf covers it.
  const centroidLat = points.reduce((s, p) => s + p[0], 0) / points.length
  const centroidLng = points.reduce((s, p) => s + p[1], 0) / points.length

  for (const [name, region] of Object.entries(REGIONS)) {
    const { minLat, minLng, maxLat, maxLng } = region.bbox
    if (centroidLat >= minLat && centroidLat <= maxLat && centroidLng >= minLng && centroidLng <= maxLng) {
      return { name, ...region }
    }
  }
  return null
}

app.get('/api/regions', (req, res) => {
  const list = Object.entries(REGIONS).map(([name, region]) => ({
    name,
    center: region.center,
    zoom: region.zoom || 12
  }))
  res.json(list)
})

app.post('/api/lookup', (req, res) => {
  const points = req.body.points // [[lat, lng], ...]
  if (!Array.isArray(points) || points.length < 3) {
    return res.status(400).json({ error: 'Need at least 3 [lat, lng] points' })
  }

  const region = findRegionForPolygon(points)
  if (!region) {
    return res.status(404).json({
      error: 'No downloaded OSM data covers this area yet. Download that city\'s .osm.pbf into osm-extract/data/ and add it to regions.json.'
    })
  }

  const sourceFlag = region.index ? ['--index', path.join(OSM_DIR, region.index)] : ['--pbf', path.join(OSM_DIR, region.pbf)]
  execFile(
    'python3',
    [path.join(OSM_DIR, 'extract.py'), ...sourceFlag, '--points-json', JSON.stringify(points), '--json'],
    { maxBuffer: 1024 * 1024 * 50, timeout: 60000 },
    (err, stdout, stderr) => {
      if (err) {
        console.error(stderr)
        return res.status(500).json({ error: 'Extraction failed', detail: stderr.toString().slice(-2000) })
      }
      try {
        const result = JSON.parse(stdout)
        result.region = region.name
        res.json(result)
      } catch (e) {
        res.status(500).json({ error: 'Could not parse extraction output' })
      }
    }
  )
})

app.get('/api/live-positions', (req, res) => {
  fs.readFile(LIVE_POSITIONS_PATH, 'utf8', (err, data) => {
    if (err) {
      return res.status(404).json({ error: 'live_positions.json not found - start live_position_simulator.py first' })
    }
    try {
      res.json(JSON.parse(data))
    } catch (e) {
      res.status(503).json({ error: 'snapshot mid-write, try again' })
    }
  })
})

app.get('/api/crowd-risk', (req, res) => {
  fs.readFile(CROWD_RISK_PATH, 'utf8', (err, data) => {
    if (err) {
      return res.status(404).json({ error: 'crowd_risk.json not found - start crowd_anomaly_agent.py first', flags: [] })
    }
    try {
      res.json(JSON.parse(data))
    } catch (e) {
      res.status(503).json({ error: 'snapshot mid-write, try again', flags: [] })
    }
  })
})

app.get('/api/crowd-intel', (req, res) => {
  fs.readFile(CROWD_INTEL_PATH, 'utf8', (err, data) => {
    if (err) {
      return res.status(404).json({ error: 'crowd_monitoring_output.json not found - start crowd-monitoring-agent/poller.js first', incidents: [] })
    }
    try {
      res.json(JSON.parse(data))
    } catch (e) {
      res.status(503).json({ error: 'snapshot mid-write, try again', incidents: [] })
    }
  })
})

app.listen(PORT, () => {
  console.log(`Map app running at http://localhost:${PORT}`)
})
