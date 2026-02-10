#!/bin/bash
# install_config_refactor.sh
# 
# Installs the refactored configuration system for RTD_SIM
# Run from RTD_SIM root directory

set -e  # Exit on error

echo "=== RTD_SIM Configuration Refactoring Installation ==="
echo ""

# Check we're in RTD_SIM directory
if [ ! -d "simulation/config" ]; then
    echo "❌ ERROR: Must run from RTD_SIM root directory"
    echo "   Current directory: $(pwd)"
    exit 1
fi

echo "✓ Found simulation/config directory"
echo ""

# Backup existing config
BACKUP_DIR="simulation/config/backup_$(date +%Y%m%d_%H%M%S)"
echo "📦 Backing up existing config to: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
cp simulation/config/*.py "$BACKUP_DIR/" 2>/dev/null || true
echo "✓ Backup complete"
echo ""

# Install new config files
echo "📥 Installing new configuration files..."

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Copy all config modules
echo "  - simulation_config.py"
cp "${SCRIPT_DIR}/simulation_config.py" simulation/config/

echo "  - infrastructure_config.py"
cp "${SCRIPT_DIR}/infrastructure_config.py" simulation/config/

echo "  - agent_config.py"
cp "${SCRIPT_DIR}/agent_config.py" simulation/config/

echo "  - analytics_config.py"
cp "${SCRIPT_DIR}/analytics_config.py" simulation/config/

echo "  - environmental_config.py"
cp "${SCRIPT_DIR}/environmental_config.py" simulation/config/

echo "  - policy_config.py"
cp "${SCRIPT_DIR}/policy_config.py" simulation/config/

echo "  - presets.py (NEW)"
cp "${SCRIPT_DIR}/presets.py" simulation/config/

echo "  - __init__.py"
cp "${SCRIPT_DIR}/config__init__.py" simulation/config/__init__.py

echo "✓ Configuration files installed"
echo ""

# Install UI component
echo "📥 Installing UI preset selector..."
echo "  - sidebar_presets.py"
cp "${SCRIPT_DIR}/sidebar_presets.py" ui/
echo "✓ UI component installed"
echo ""

# Test imports
echo "🧪 Testing imports..."
python3 << 'PYEOF'
import sys
sys.path.insert(0, '.')

try:
    from simulation.config import SimulationConfig, ConfigurationPresets
    print("  ✓ SimulationConfig imports successfully")
    
    from simulation.config import (
        InfrastructureConfig,
        AgentConfig,
        AnalyticsConfig,
        EnvironmentalConfig,
        PolicyConfig
    )
    print("  ✓ All sub-configs import successfully")
    
    # Test preset loading
    presets = ConfigurationPresets.list_presets()
    print(f"  ✓ Found {len(presets)} presets")
    
    # Test creating a preset
    config = ConfigurationPresets.high_ev_demand()
    assert config.num_agents == 100
    assert config.infrastructure.grid_capacity_mw == 30.0
    print("  ✓ Presets work correctly")
    
    # Test backward compatibility
    config2 = SimulationConfig()
    config2.grid_capacity_mw = 50
    assert config2.infrastructure.grid_capacity_mw == 50
    print("  ✓ Backward compatibility works")
    
    print("\n✅ All tests passed!")
    
except Exception as e:
    print(f"\n❌ Import test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYEOF

echo ""
echo "=== Installation Complete ==="
echo ""
echo "📚 Documentation: CONFIG_REFACTORING_GUIDE.md"
echo ""
echo "🎯 Quick Start:"
echo "  from simulation.config.presets import ConfigurationPresets"
echo "  config = ConfigurationPresets.high_ev_demand()"
echo ""
echo "✅ Ready to use!"
