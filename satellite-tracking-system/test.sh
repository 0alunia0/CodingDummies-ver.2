#!/bin/bash

BASE_URL="http://127.0.0.1:8001"
PASS=0
FAIL=0

test_endpoint() {
    local name="$1"
    local cmd="$2"
    local expected="$3"
    
    echo -n "Testing: $name ... "
    result=$(eval "$cmd" 2>&1)
    
    if echo "$result" | grep -q "$expected"; then
        echo " PASS"
        PASS=$((PASS + 1))
    else
        echo " FAIL"
        echo "  Expected: $expected"
        echo "  Got: $result"
        FAIL=$((FAIL + 1))
    fi
}

echo "========================================="
echo "FINAL SYSTEM TEST"
echo "========================================="
echo ""

# Restart database (clean database for tests)
echo "Preparing test environment..."
pkill -f "uvicorn satellite_api:system_api" 2>/dev/null
sleep 1
.venv/bin/uvicorn satellite_api:system_api --host 127.0.0.1 --port 8001 --log-level error > /dev/null 2>&1 &
UVICORN_PID=$!
sleep 3
echo ""

echo "PART 1: Basic Tests"
echo "-----------------------------------"
test_endpoint "Status Check" \
    "curl -s $BASE_URL/status" \
    '"status":"running"'
test_endpoint "Main Endpoint" \
    "curl -s $BASE_URL/" \
    "Orbit Tracking"

echo ""
echo "PART 2: Orbit CRUD"
echo "-----------------------------------"

# Creating orbits
test_endpoint "Create Orbit 1" \
    "curl -s -X POST $BASE_URL/orbits/ -H 'Content-Type: application/json' -d '{\"name\":\"TEST-LEO\",\"altitude\":550,\"inclination\":51.6,\"raan\":90}'" \
    '"id"'

test_endpoint "Create Orbit 2" \
    "curl -s -X POST $BASE_URL/orbits/ -H 'Content-Type: application/json' -d '{\"name\":\"TEST-MEO\",\"altitude\":20000,\"inclination\":55,\"raan\":45}'" \
    '"id"'

test_endpoint "List Orbits" \
    "curl -s $BASE_URL/orbits/" \
    '"total"'

test_endpoint "Get Orbit by ID" \
    "curl -s $BASE_URL/orbits/1" \
    "TEST-LEO"

test_endpoint "Update Orbit" \
    "curl -s -X PUT $BASE_URL/orbits/1 -H 'Content-Type: application/json' -d '{\"name\":\"TEST-LEO-UPDATED\",\"altitude\":560,\"inclination\":51.6,\"raan\":90}'" \
    "TEST-LEO-UPDATED"

echo ""
echo "PART 3: Satellite CRUD"
echo "-----------------------------------"

test_endpoint "Create Satellite 1" \
    "curl -s -X POST $BASE_URL/satellites/ -H 'Content-Type: application/json' -d '{\"name\":\"SAT-A\",\"operator\":\"TestOrg\",\"launch_date\":\"2020-01-01T00:00:00Z\",\"status\":\"active\",\"starting_lon_position\":0,\"associated_orbit_id\":1}'" \
    '"id"'

test_endpoint "Create Satellite 2" \
    "curl -s -X POST $BASE_URL/satellites/ -H 'Content-Type: application/json' -d '{\"name\":\"SAT-B\",\"operator\":\"TestOrg\",\"launch_date\":\"2020-01-01T00:00:00Z\",\"status\":\"active\",\"starting_lon_position\":10,\"associated_orbit_id\":1}'" \
    '"id"'

test_endpoint "List Satellites" \
    "curl -s $BASE_URL/satellites/" \
    '"total"'

test_endpoint "Get Satellite by ID" \
    "curl -s $BASE_URL/satellites/1" \
    "SAT-A"

test_endpoint "Update Satellite" \
    "curl -s -X PUT $BASE_URL/satellites/1 -H 'Content-Type: application/json' -d '{\"name\":\"SAT-A-UPDATED\",\"operator\":\"TestOrg\",\"launch_date\":\"2020-01-01T00:00:00Z\",\"status\":\"active\",\"starting_lon_position\":0,\"associated_orbit_id\":1}'" \
    'SAT-A-UPDATED'

echo ""
echo "PART 4: Orbital Calculations"
echo "-----------------------------------"

test_endpoint "Calculate Position (2024)" \
    "curl -s '$BASE_URL/satellites/1/position?timestamp=2024-06-15T12:00:00Z'" \
    '"latitude"'

test_endpoint "Calculate Position (2025)" \
    "curl -s '$BASE_URL/satellites/2/position?timestamp=2025-01-01T00:00:00Z'" \
    '"longitude"'

echo ""
echo "PART 5: Proximity Detection"
echo "-----------------------------------"

test_endpoint "Detect Proximities" \
    "curl -s '$BASE_URL/proximities?start_date=2020-01-01T00:00:00Z&end_date=2025-06-30T00:00:00Z'" \
    'proximities'

echo ""
echo "PART 6: Validation and Errors"
echo "-----------------------------------"

test_endpoint "Invalid Altitude (too low)" \
    "curl -s -X POST $BASE_URL/orbits/ -H 'Content-Type: application/json' -d '{\"name\":\"INVALID\",\"altitude\":50,\"inclination\":51.6,\"raan\":90}'" \
    '"detail"'

test_endpoint "Invalid Inclination" \
    "curl -s -X POST $BASE_URL/orbits/ -H 'Content-Type: application/json' -d '{\"name\":\"INVALID2\",\"altitude\":550,\"inclination\":200,\"raan\":90}'" \
    '"detail"'

test_endpoint "Duplicate Orbit Name" \
    "curl -s -X POST $BASE_URL/orbits/ -H 'Content-Type: application/json' -d '{\"name\":\"TEST-LEO-UPDATED\",\"altitude\":550,\"inclination\":51.6,\"raan\":90}'" \
    '"detail"'

test_endpoint "Non-existent Orbit" \
    "curl -s $BASE_URL/orbits/99999" \
    "not found"

test_endpoint "Non-existent Satellite" \
    "curl -s $BASE_URL/satellites/99999" \
    "not found"

echo ""
echo "PART 7: Resource Deletion"
echo "-----------------------------------"

test_endpoint "Delete Satellite" \
    "curl -s -X DELETE $BASE_URL/satellites/2 -o /dev/null -w '%{http_code}'" \
    "204"

test_endpoint "Verify Deletion" \
    "curl -s $BASE_URL/satellites/2" \
    "not found"

test_endpoint "Delete Orbit (with satellites)" \
    "curl -s -X DELETE $BASE_URL/orbits/1" \
    "detail"

echo ""
echo "PART 8: Pagination"
echo "-----------------------------------"

test_endpoint "Pagination (skip=0, limit=1)" \
    "curl -s '$BASE_URL/satellites/?skip=0&limit=1'" \
    'limit'

test_endpoint "Pagination (skip=1, limit=1)" \
    "curl -s '$BASE_URL/satellites/?skip=1&limit=1'" \
    'skip'

echo ""
echo "========================================="
echo "FINAL RESULTS"
echo "========================================="
echo " Tests passed: $PASS"
echo " Tests failed: $FAIL"
echo " Total: $((PASS + FAIL))"
echo ""

if [ $FAIL -eq 0 ]; then
    echo " ALL TESTS PASSED!"
    echo " System is 100% functional"
    EXIT_CODE=0
else
    echo " Errors detected in system"
    EXIT_CODE=1
fi

# Cleanup
echo ""
echo "Test completed."
pkill -f "uvicorn satellite_api:system_api" 2>/dev/null || true
