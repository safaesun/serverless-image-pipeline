#!/bin/bash
set -e
mkdir -p layer/python && cd layer
pip3 install --platform manylinux2014_x86_64 --implementation cp \
  --python-version 3.12 --only-binary=:all: --upgrade \
  --target python pillow
zip -r pillow-layer.zip python
aws lambda publish-layer-version \
  --layer-name pillow-layer \
  --zip-file fileb://pillow-layer.zip \
  --compatible-runtimes python3.12 \
  --compatible-architectures x86_64