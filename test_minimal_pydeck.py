
import streamlit as st
import pydeck as pdk
import pandas as pd

st.title("Minimal Pydeck Test")

# Test data
data = pd.DataFrame({
    'lat': [55.9533, 55.9486, 55.9445],
    'lon': [-3.1883, -3.2008, -3.1619],
    'color': [[255, 0, 0], [0, 255, 0], [0, 0, 255]],
    'name': ['Point 1', 'Point 2', 'Point 3'],
})

st.write("Test data:")
st.dataframe(data)

# Create layer
layer = pdk.Layer(
    'ScatterplotLayer',
    data,
    get_position='[lon, lat]',
    get_color='color',
    get_radius=100,
    pickable=True,
)

# Create view
view_state = pdk.ViewState(
    latitude=55.95,
    longitude=-3.19,
    zoom=12,
    pitch=0,
)

# Try different map styles
map_style = st.selectbox(
    "Map Style",
    [
        "mapbox://styles/mapbox/light-v10",
        "mapbox://styles/mapbox/dark-v10",
        "mapbox://styles/mapbox/streets-v11",
        "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    ]
)

# Create deck
deck = pdk.Deck(
    layers=[layer],
    initial_view_state=view_state,
    map_style=map_style,
    tooltip={'text': '{name}'},
)

st.pydeck_chart(deck)

st.write("If you see colored dots on a map above, pydeck is working!")
st.write("If you only see dots but no map, the basemap isn't loading.")
