"""
Test script for Custom Location functionality.
Run this to test geocoding and map independently of the full app.

Usage: streamlit run location_test.py
"""

import streamlit as st
import streamlit.components.v1 as components
from typing import Optional
import json

st.title("🧪 Location Picker Test")

# ============================================================================
# Test 1: Geocoding
# ============================================================================
st.header("Test 1: Geocoding")

def geocode_place(query: str) -> Optional[dict]:
    """Geocode via Nominatim."""
    try:
        import requests
        st.write(f"🔍 Attempting to geocode: `{query}`")
        url = "https://nominatim.openstreetmap.org/search"
        resp = requests.get(
            url,
            params={"q": query.strip(), "format": "json", "limit": 1},
            headers={"User-Agent": "RTD-SIM/1.0"},
            timeout=8,
        )
        st.write(f"📡 Response status: {resp.status_code}")
        results = resp.json()
        st.write(f"📦 Results: {results}")
        if results:
            r = results[0]
            return {
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "display_name": r["display_name"],
            }
    except Exception as e:
        st.error(f"❌ Geocoding failed: {e}")
    return None

text = st.text_input("Enter place name", value="Hawick")

# Button OUTSIDE form context
if st.button("🔍 Test Geocode"):
    with st.spinner("Geocoding..."):
        result = geocode_place(text)
    if result:
        st.success(f"✅ Found: {result['display_name']}")
        st.json(result)
    else:
        st.error("❌ Geocoding failed")

st.markdown("---")

# ============================================================================
# Test 2: Interactive Map
# ============================================================================
st.header("Test 2: Interactive Map")

st.write("Click anywhere on the map below to place a pin.")

leaflet_html = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    body { margin:0; padding:0; }
    #map { height: 400px; width: 100%; }
    #output { padding: 10px; background: #f0f0f0; font-family: monospace; }
  </style>
</head>
<body>
  <div id="map"></div>
  <div id="output">Click the map to place pins. Coords will appear here.</div>
  <script>
    var map = L.map('map').setView([55.4, -2.8], 7);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap'
    }).addTo(map);

    var pins = [];
    var output = document.getElementById('output');

    map.on('click', function(e) {
      var lat = e.latlng.lat.toFixed(4);
      var lon = e.latlng.lng.toFixed(4);
      
      L.marker([lat, lon]).addTo(map)
        .bindPopup('📍 ' + lat + ', ' + lon).openPopup();
      
      pins.push(lat + ',' + lon);
      output.textContent = 'Pins: ' + pins.join(' ; ');
    });
  </script>
</body>
</html>
"""

components.html(leaflet_html, height=500)

st.caption("👆 If you can click the map and see markers appear, the map component works.")

st.markdown("---")

# ============================================================================
# Test 3: Form context issue
# ============================================================================
st.header("Test 3: Button in vs out of form")

st.subheader("Button OUTSIDE form (should work)")
if st.button("Click me (outside)", key="btn1"):
    st.success("✅ Outside button clicked!")

st.subheader("Button INSIDE form")
with st.form("test_form"):
    st.write("This button is inside a form")
    submitted = st.form_submit_button("Click me (inside form)")
    if submitted:
        st.success("✅ Form button clicked!")

st.markdown("---")
st.info("**Diagnosis:** If Test 1 fails, check your network. If Test 2 fails, check Streamlit version and browser console for errors. If Test 3 shows different behavior, buttons in forms need special handling.")