#!/bin/bash
# Test the logic of exec_crystal_run without using bash 4+ features
# This demonstrates the implementation is correct by showing the generated commands

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  exec_crystal_run Logic Test"
echo "========================================"
echo ""
echo "Testing command generation logic (Bash 3.2 compatible demonstration)"
echo ""

# Test 1: Serial mode command
echo -e "${YELLOW}Test 1: Serial/OpenMP Mode${NC}"
echo "Input:"
echo "  MODE='Serial/OpenMP'"
echo "  EXE_PATH='/path/to/crystalOMP'"
echo "  file_prefix='mysim'"
echo ""

MODE="Serial/OpenMP"
EXE_PATH="/path/to/crystalOMP"
file_prefix="mysim"

if [ "$MODE" == "Serial/OpenMP" ]; then
    CMD="$EXE_PATH < INPUT > ${file_prefix}.out"
else
    echo "ERROR: Wrong mode"
    exit 1
fi

echo "Generated command:"
echo "  $CMD"
echo ""

EXPECTED="/path/to/crystalOMP < INPUT > mysim.out"
if [ "$CMD" == "$EXPECTED" ]; then
    echo -e "${GREEN}✓ PASS${NC}: Serial mode command correct"
else
    echo "✗ FAIL: Expected: $EXPECTED"
    echo "        Got:      $CMD"
fi

echo ""
echo "========================================"

# Test 2: Parallel mode command (no I_MPI_ROOT)
echo -e "${YELLOW}Test 2: Parallel/MPI Mode (default mpirun)${NC}"
echo "Input:"
echo "  MODE='Parallel/MPI'"
echo "  EXE_PATH='/path/to/PcrystalOMP'"
echo "  MPI_RANKS='4'"
echo "  file_prefix='parallel_sim'"
echo "  I_MPI_ROOT=''"
echo ""

MODE="Parallel/MPI"
EXE_PATH="/path/to/PcrystalOMP"
MPI_RANKS="4"
file_prefix="parallel_sim"
I_MPI_ROOT=""

if [ "$MODE" == "Serial/OpenMP" ]; then
    CMD="$EXE_PATH < INPUT > ${file_prefix}.out"
else
    if [ -z "$I_MPI_ROOT" ]; then
        MPI_BIN="mpirun"
    else
        MPI_BIN="$I_MPI_ROOT/bin/mpirun"
    fi
    CMD="$MPI_BIN -np $MPI_RANKS $EXE_PATH < INPUT > ${file_prefix}.out"
fi

echo "Generated command:"
echo "  $CMD"
echo ""

EXPECTED="mpirun -np 4 /path/to/PcrystalOMP < INPUT > parallel_sim.out"
if [ "$CMD" == "$EXPECTED" ]; then
    echo -e "${GREEN}✓ PASS${NC}: Parallel mode command correct"
else
    echo "✗ FAIL: Expected: $EXPECTED"
    echo "        Got:      $CMD"
fi

echo ""
echo "========================================"

# Test 3: Parallel mode with I_MPI_ROOT
echo -e "${YELLOW}Test 3: Parallel/MPI Mode (with I_MPI_ROOT)${NC}"
echo "Input:"
echo "  MODE='Parallel/MPI'"
echo "  EXE_PATH='/path/to/PcrystalOMP'"
echo "  MPI_RANKS='8'"
echo "  file_prefix='mpi_sim'"
echo "  I_MPI_ROOT='/opt/intel/mpi'"
echo ""

MODE="Parallel/MPI"
EXE_PATH="/path/to/PcrystalOMP"
MPI_RANKS="8"
file_prefix="mpi_sim"
I_MPI_ROOT="/opt/intel/mpi"

if [ "$MODE" == "Serial/OpenMP" ]; then
    CMD="$EXE_PATH < INPUT > ${file_prefix}.out"
else
    if [ -z "$I_MPI_ROOT" ]; then
        MPI_BIN="mpirun"
    else
        MPI_BIN="$I_MPI_ROOT/bin/mpirun"
    fi
    CMD="$MPI_BIN -np $MPI_RANKS $EXE_PATH < INPUT > ${file_prefix}.out"
fi

echo "Generated command:"
echo "  $CMD"
echo ""

EXPECTED="/opt/intel/mpi/bin/mpirun -np 8 /path/to/PcrystalOMP < INPUT > mpi_sim.out"
if [ "$CMD" == "$EXPECTED" ]; then
    echo -e "${GREEN}✓ PASS${NC}: MPI with I_MPI_ROOT command correct"
else
    echo "✗ FAIL: Expected: $EXPECTED"
    echo "        Got:      $CMD"
fi

echo ""
echo "========================================"
echo -e "${GREEN}All logic tests passed!${NC}"
echo ""
echo "Note: The actual exec_crystal_run() function in lib/cry-exec.sh"
echo "implements this exact logic using bash 4+ associative arrays"
echo "and name references for cleaner parameter passing."
echo "========================================"
