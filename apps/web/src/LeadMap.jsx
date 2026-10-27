import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

const BAND = { hot: '#e8590c', warm: '#f59f00', cool: '#868e96' };

// Map of leads coloured by opportunity band. Tiles load from tile.openstreetmap.org only while this view is open.
export default function LeadMap({ leads, selectedId, onSelect }) {
  const box = useRef(null), map = useRef(null), layer = useRef(null), fitted = useRef(null);

  useEffect(() => {
    map.current = L.map(box.current, { scrollWheelZoom: true });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => { map.current.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    layer.current.clearLayers();
    const points = leads.filter(l => l.lat != null && l.lon != null);
    points.forEach(lead => {
      const band = lead.opportunity?.band || 'cool', selected = lead.id === selectedId;
      L.circleMarker([lead.lat, lead.lon], { radius: selected ? 11 : 8, color: selected ? '#173e35' : '#fff', weight: selected ? 3 : 1.5,
        fillColor: BAND[band], fillOpacity: .9 })
        .bindTooltip(`${lead.opportunity?.score ?? ''} · ${lead.name}`)
        .on('click', () => onSelect(lead.id)).addTo(layer.current);
    });
    if (points.length && fitted.current !== leads) map.current.fitBounds(L.latLngBounds(points.map(l => [l.lat, l.lon])).pad(.15), { maxZoom: 16 });
    fitted.current = leads;
  }, [leads, selectedId, onSelect]);

  return <div className="lead-map" ref={box} role="region" aria-label="Map of businesses"/>;
}
