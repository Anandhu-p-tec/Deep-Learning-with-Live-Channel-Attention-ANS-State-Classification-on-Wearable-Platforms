#!/usr/bin/env python3
"""Test if the model loads and works correctly."""

import sys
import numpy as np

sys.path.insert(0, '.')

from model.model_utils import load_or_create_model, CLASSES, MODEL_WINDOW_SAMPLES, mc_dropout_predict

print("Loading model...")
model = load_or_create_model()
print(f"Model type: {type(model).__name__}")
print(f"Classes: {CLASSES}")
print(f"Window samples: {MODEL_WINDOW_SAMPLES}")

# Test prediction
print("\nTesting prediction with random window...")
window = np.random.rand(30, 4).astype(np.float32)
print(f"Test window shape: {window.shape}")

result = mc_dropout_predict(model, window, T=3)
print(f"\n✅ Prediction Results:")
print(f"  Predicted Class: {result['predicted_class']}")
print(f"  Confidence: {result['confidence']}%")
print(f"  Dominant Sensor: {result['dominant_sensor']}")
print(f"  All Probabilities: {result['all_probs']}")

print("\n✅ Model loaded and tested successfully!")
print("Ready to run Streamlit app with real sensor data!")
