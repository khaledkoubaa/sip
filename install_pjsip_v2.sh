#!/bin/bash
# install_pjsip.sh - Install PJSIP with Python bindings

set -e

echo "=========================================="
echo "PJSIP Installation for SIP Client"
echo "=========================================="

# Install dependencies
echo "[1/6] Installing dependencies..."
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    python3-dev \
    libasound2-dev \
    libssl-dev \
    libopus-dev \
    libv4l-dev \
    libsdl2-dev \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    wget \
    swig

# Download PJSIP
PJSIP_VERSION="2.14.1"
PJSIP_DIR="pjproject-${PJSIP_VERSION}"

echo "[2/6] Downloading PJSIP ${PJSIP_VERSION}..."
cd /tmp
if [ ! -f "pjproject-${PJSIP_VERSION}.tar.gz" ]; then
    wget "https://github.com/pjsip/pjproject/archive/refs/tags/${PJSIP_VERSION}.tar.gz" -O "pjproject-${PJSIP_VERSION}.tar.gz"
fi

echo "[3/6] Extracting..."
rm -rf ${PJSIP_DIR}
tar xzf pjproject-${PJSIP_VERSION}.tar.gz

cd ${PJSIP_DIR}

# Configure
echo "[4/6] Configuring PJSIP..."
./configure --enable-shared --with-python=$(which python3)

# Build
echo "[5/6] Building PJSIP (this takes a while)..."
make -j$(nproc)
sudo make install
sudo ldconfig

# Build Python bindings
echo "[6/6] Building Python bindings..."
cd pjsip-apps/src/swig/python
make
sudo python3 setup.py install

echo ""
echo "=========================================="
echo "PJSIP installed successfully!"
echo "=========================================="
python3 -c "import pjsua2; print(f'pjsua2 version: OK')"