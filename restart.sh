#!/bin/bash
# 🔄 Seahorse Agent - Fresh Start Script
# สคริปต์สำหรับ restart ระบบใหม่ด้วย code ล่าสุด

set -e

PROJECT_ROOT="/Users/weerachit/Documents/seahorse"
cd "$PROJECT_ROOT"

echo "🔄 Seahorse Agent - Fresh Start"
echo "================================"

# Step 1: Stop old processes
echo ""
echo "🛑 Step 1: หยุด old processes..."
pkill -9 seahorse 2>/dev/null || true
pkill -9 seahorse-router 2>/dev/null || true
sleep 2
echo "✅ Old processes terminated"

# Step 2: Clear Python cache
echo ""
echo "🧹 Step 2: Clear Python cache..."
find python -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find python -name "*.pyc" -delete 2>/dev/null || true
echo "✅ Python cache cleared"

# Step 3: Verify binary is fresh
echo ""
echo "🔍 Step 3: Verify binary..."
BINARY_TIME=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" target/debug/seahorse)
echo "   Binary last modified: $BINARY_TIME"

# Check if binary is recent (within 10 minutes)
if [ $(uname) = "Darwin" ]; then
    BINARY_EPOCH=$(stat -f "%m" target/debug/seahorse)
    CURRENT_EPOCH=$(date +%s)
    DIFF=$((CURRENT_EPOCH - BINARY_EPOCH))
    if [ $DIFF -lt 600 ]; then
        echo "   ✅ Binary is fresh ($diff seconds ago)"
    else
        echo "   ⚠️  Binary is old ($diff seconds ago)"
        echo "   📦 Rebuilding..."
        cargo build --workspace
    fi
fi

# Step 4: Quick test
echo ""
echo "🧪 Step 4: Quick test..."
uv run python -c "
import sys
sys.path.insert(0, 'python')
from seahorse_ai.core.nodes import _safe_create_message
msg = _safe_create_message({'role': 'user', 'content': 'test', 'model': 'gpt-4'})
print('✅ Code ล่าสุดทำงานได้!')
"

# Step 5: Start fresh
echo ""
echo "🚀 Step 5: พร้อมใช้งาน!"
echo ""
echo "เลือกวิธีรัน:"
echo ""
echo "1️⃣  รัน CLI Chat:"
echo "   ./target/debug/seahorse chat"
echo ""
echo "2️⃣  รัน Router แยก:"
echo "   ./target/debug/seahorse-router"
echo ""
echo "3️⃣  รันด้วย Nix:"
echo "   nix develop --command ./target/debug/seahorse chat"
echo ""
echo "✅ ระบบพร้อมใช้งาน!"
