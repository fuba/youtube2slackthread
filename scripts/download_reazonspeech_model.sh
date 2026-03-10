#!/bin/bash
# Download ReazonSpeech K2 model and Silero VAD for sherpa-onnx
set -euo pipefail

MODELS_DIR="${1:-./models}"
mkdir -p "$MODELS_DIR"

MODEL_NAME="sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01"
MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${MODEL_NAME}.tar.bz2"
VAD_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"

# Download ReazonSpeech K2 model
if [ ! -d "$MODELS_DIR/$MODEL_NAME" ]; then
    echo "Downloading ReazonSpeech K2 model..."
    curl -L "$MODEL_URL" -o "$MODELS_DIR/${MODEL_NAME}.tar.bz2"
    echo "Extracting..."
    tar -xjf "$MODELS_DIR/${MODEL_NAME}.tar.bz2" -C "$MODELS_DIR"
    rm "$MODELS_DIR/${MODEL_NAME}.tar.bz2"
    echo "ReazonSpeech K2 model downloaded to $MODELS_DIR/$MODEL_NAME"
else
    echo "ReazonSpeech K2 model already exists at $MODELS_DIR/$MODEL_NAME"
fi

# Download Silero VAD model
if [ ! -f "$MODELS_DIR/silero_vad.onnx" ]; then
    echo "Downloading Silero VAD model..."
    curl -L "$VAD_URL" -o "$MODELS_DIR/silero_vad.onnx"
    echo "Silero VAD model downloaded to $MODELS_DIR/silero_vad.onnx"
else
    echo "Silero VAD model already exists at $MODELS_DIR/silero_vad.onnx"
fi

echo "Done! Models are ready in $MODELS_DIR"
echo ""
echo "Model sizes:"
ls -lh "$MODELS_DIR/$MODEL_NAME/"*.onnx "$MODELS_DIR/silero_vad.onnx" 2>/dev/null || true
