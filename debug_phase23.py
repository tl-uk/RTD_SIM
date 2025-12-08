#!/usr/bin/env python3
"""
Debug script for Phase 2.3 visualization issues

Checks:
1. Pydeck installation and version
2. Map rendering capability
3. Animation timing
4. Data format issues
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def check_dependencies():
    """Check if all required packages are installed."""
    print("=" * 70)
    print("DEPENDENCY CHECK")
    print("=" * 70)
    
    required = {
        'pydeck': '0.9.0',
        'streamlit': '1.0.0',
        'pandas': '1.0.0',
        'numpy': '1.20.0',
    }
    
    for package, min_version in required.items():
        try:
            module = __import__(package)
            version = getattr(module, '__version__', 'unknown')
            print(f"✅ {package:15s} {version:10s}")
        except ImportError:
            print(f"❌ {package:15s} NOT INSTALLED")
            return False
    
    return True


def test_pydeck_basic():
    """Test basic pydeck functionality."""
    print("\n" + "=" * 70)
    print("PYDECK BASIC TEST")
    print("=" * 70)
    
    try:
        import pydeck as pdk
        import pandas as pd
        
        # Create simple test data
        data = pd.DataFrame({
            'lat': [55.9533],
            'lon': [-3.1883],
            'color': [[255, 0, 0]],
        })
        
        # Create layer
        layer = pdk.Layer(
            'ScatterplotLayer',
            data,
            get_position='[lon, lat]',
            get_color='color',
            get_radius=100,
        )
        
        # Create deck
        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=pdk.ViewState(
                latitude=55.9533,
                longitude=-3.1883,
                zoom=12,
                pitch=0,
            ),
            map_style='mapbox://styles/mapbox/light-v10',
        )
        
        print("✅ Pydeck deck created successfully")
        print(f"   Map style: {deck.map_style}")
        print(f"   Layers: {len(deck.layers)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Pydeck test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_map_styles():
    """Test different map styles to find one that works."""
    print("\n" + "=" * 70)
    print("MAP STYLE TEST")
    print("=" * 70)
    
    try:
        import pydeck as pdk
        
        styles = [
            'mapbox://styles/mapbox/light-v10',
            'mapbox://styles/mapbox/dark-v10',
            'mapbox://styles/mapbox/streets-v11',
            'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
            'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
        ]
        
        for style in styles:
            try:
                deck = pdk.Deck(
                    layers=[],
                    map_style=style,
                )
                print(f"✅ {style}")
            except Exception as e:
                print(f"❌ {style} - {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Map style test failed: {e}")
        return False


def test_animation_timing():
    """Test animation controller timing."""
    print("\n" + "=" * 70)
    print("ANIMATION TIMING TEST")
    print("=" * 70)
    
    try:
        from visualiser.animation_controller import AnimationController
        import time
        
        anim = AnimationController(total_steps=100, fps=10)
        
        print(f"FPS: {anim.fps}")
        print(f"Frame duration: {anim.frame_duration:.3f}s")
        
        # Test update timing
        anim.play()
        updates = 0
        start = time.time()
        
        for _ in range(50):  # Test 50 frames
            if anim.update():
                updates += 1
            time.sleep(0.01)  # Small sleep
        
        elapsed = time.time() - start
        actual_fps = updates / elapsed if elapsed > 0 else 0
        
        print(f"\nTest results:")
        print(f"  Updates: {updates}")
        print(f"  Elapsed: {elapsed:.2f}s")
        print(f"  Actual FPS: {actual_fps:.1f}")
        
        if actual_fps < 5:
            print("⚠️  FPS is low - animation may appear slow")
        else:
            print("✅ Animation timing looks good")
        
        return True
        
    except Exception as e:
        print(f"❌ Animation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_data_format():
    """Test data adapter output format."""
    print("\n" + "=" * 70)
    print("DATA FORMAT TEST")
    print("=" * 70)
    
    try:
        from visualiser.data_adapters import AgentDataAdapter, RouteDataAdapter
        
        # Test agent data
        agent_states = [
            {
                'agent_id': 'test_1',
                'location': (-3.1883, 55.9533),
                'mode': 'bike',
                'arrived': False,
            }
        ]
        
        agent_df = AgentDataAdapter.agents_to_dataframe(agent_states, 0)
        print("\nAgent DataFrame:")
        print(agent_df)
        print(f"Columns: {list(agent_df.columns)}")
        print(f"Dtypes: {agent_df.dtypes.to_dict()}")
        
        # Test route data
        route_states = [
            {
                'agent_id': 'test_1',
                'route': [(-3.19, 55.95), (-3.20, 55.96), (-3.21, 55.97)],
                'mode': 'bike',
            }
        ]
        
        route_df = RouteDataAdapter.routes_to_dataframe(route_states)
        print("\nRoute DataFrame:")
        print(route_df)
        print(f"Columns: {list(route_df.columns)}")
        
        # Check path format
        if not route_df.empty:
            path = route_df.iloc[0]['path']
            print(f"\nPath format: {type(path)}")
            print(f"Path example: {path}")
            
            # Verify it's [[lon, lat], [lon, lat], ...]
            if isinstance(path, list) and len(path) > 0:
                if isinstance(path[0], list) and len(path[0]) == 2:
                    print("✅ Path format is correct")
                else:
                    print("❌ Path format is wrong - should be [[lon, lat], ...]")
        
        return True
        
    except Exception as e:
        print(f"❌ Data format test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def create_minimal_test_app():
    """Create minimal test Streamlit app."""
    print("\n" + "=" * 70)
    print("CREATING MINIMAL TEST APP")
    print("=" * 70)
    
    test_app = """
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
"""
    
    test_path = PROJECT_ROOT / "test_minimal_pydeck.py"
    with open(test_path, 'w') as f:
        f.write(test_app)
    
    print(f"✅ Created: {test_path}")
    print("\nTo test, run:")
    print(f"  streamlit run {test_path}")
    print("\nThis will help identify if the issue is:")
    print("  - Pydeck installation")
    print("  - Map style/basemap loading")
    print("  - Data format")
    print("  - Something else")


def main():
    """Run all diagnostics."""
    print("\n")
    print("=" * 70)
    print("RTD_SIM PHASE 2.3 DIAGNOSTIC TOOL")
    print("=" * 70)
    
    results = []
    
    # Run tests
    results.append(("Dependencies", check_dependencies()))
    results.append(("Pydeck Basic", test_pydeck_basic()))
    results.append(("Map Styles", test_map_styles()))
    results.append(("Animation Timing", test_animation_timing()))
    results.append(("Data Format", test_data_format()))
    
    # Create test app
    create_minimal_test_app()
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name:20s} {status}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n✅ All tests passed!")
        print("\nIf map still doesn't show in main app, the issue is likely:")
        print("  1. Internet connection (basemaps require online access)")
        print("  2. Firewall blocking map tile requests")
        print("  3. Browser compatibility (try Chrome/Edge)")
    else:
        print("\n❌ Some tests failed - see details above")
    
    print("\n" + "=" * 70)
    print("NEXT STEPS")
    print("=" * 70)
    print("1. Run: streamlit run test_minimal_pydeck.py")
    print("2. Try different map styles from dropdown")
    print("3. Check browser console (F12) for errors")
    print("4. Report which map style works (if any)")


if __name__ == '__main__':
    main()