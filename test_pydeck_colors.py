import streamlit as st
import pydeck as pdk
import pandas as pd

st.title("🎨 Pydeck Color Test")

df = pd.DataFrame({
    'lat': [55.95, 55.96, 55.97],
    'lon': [-3.19, -3.18, -3.17],
    'r': [255, 0, 0],      # RED
    'g': [0, 255, 0],      # GREEN  
    'b': [0, 0, 255],      # BLUE
})

st.write("Expected: 3 dots - RED, GREEN, BLUE")
st.write("DataFrame contents:", df)

layer = pdk.Layer(
    'ScatterplotLayer',
    data=df,
    get_position='[lon, lat]',
    get_fill_color='[r, g, b]',
    get_radius=100,
    pickable=True
)

st.pydeck_chart(pdk.Deck(
    layers=[layer],
    initial_view_state=pdk.ViewState(latitude=55.96, longitude=-3.18, zoom=11)
))