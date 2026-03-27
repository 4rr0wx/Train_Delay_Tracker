import { createClient } from 'hafas-client'
import { profile as oebbProfile } from 'hafas-client/p/oebb/index.js'
import express from 'express'

const hafas = createClient(oebbProfile, 'train-delay-tracker/1.0')
const app = express()

app.get('/health', (_req, res) => res.json({ ok: true }))

function parseBool(val, def = true) {
  if (val === undefined) return def
  return val !== 'false'
}

app.get('/stops/:id/departures', async (req, res) => {
  try {
    const results = await hafas.departures(req.params.id, {
      duration:        parseInt(req.query.duration) || 120,
      bus:             parseBool(req.query.bus, false),
      tram:            parseBool(req.query.tram, false),
      ferry:           parseBool(req.query.ferry, false),
      national:        parseBool(req.query.national),
      nationalExpress: parseBool(req.query.nationalExpress),
      interregional:   parseBool(req.query.interregional),
      regional:        parseBool(req.query.regional),
      suburban:        parseBool(req.query.suburban),
    })
    res.json(results)
  } catch (err) {
    console.error('departures error:', err.message)
    res.status(502).json({ isHafasError: true, message: err.message })
  }
})

app.get('/stops/:id/arrivals', async (req, res) => {
  try {
    const results = await hafas.arrivals(req.params.id, {
      duration:        parseInt(req.query.duration) || 120,
      bus:             parseBool(req.query.bus, false),
      tram:            parseBool(req.query.tram, false),
      ferry:           parseBool(req.query.ferry, false),
      national:        parseBool(req.query.national),
      nationalExpress: parseBool(req.query.nationalExpress),
      interregional:   parseBool(req.query.interregional),
      regional:        parseBool(req.query.regional),
      suburban:        parseBool(req.query.suburban),
    })
    res.json(results)
  } catch (err) {
    console.error('arrivals error:', err.message)
    res.status(502).json({ isHafasError: true, message: err.message })
  }
})

app.get('/trips/:id', async (req, res) => {
  try {
    const trip = await hafas.trip(req.params.id, { polyline: false })
    res.json({ trip })
  } catch (err) {
    console.error('trip error:', err.message)
    res.status(502).json({ isHafasError: true, message: err.message })
  }
})

app.get('/locations', async (req, res) => {
  try {
    const results = await hafas.locations(req.query.query || '', {
      results: parseInt(req.query.results) || 10,
    })
    res.json(results)
  } catch (err) {
    console.error('locations error:', err.message)
    res.status(500).json({ error: err.message })
  }
})

const PORT = process.env.PORT || 3000
app.listen(PORT, '0.0.0.0', () =>
  console.log(`hafas-oebb listening on port ${PORT}`)
)
