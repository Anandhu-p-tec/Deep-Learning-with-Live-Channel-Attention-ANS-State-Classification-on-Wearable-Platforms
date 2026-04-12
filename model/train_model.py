"""Train ANS classifier on hardware-matched normalized ranges."""

from __future__ import annotations

import os
import sys
from typing import Tuple

import numpy as np
import tensorflow as tf


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
	sys.path.append(PROJECT_ROOT)

from model.model_utils import CLASSES, build_model


CLASS_RANGES = {
	"Normal Baseline": {
		"gsr": (0.20, 0.45),
		"spo2": (0.60, 0.90),
		"temp": (0.30, 0.42),
		"accel": (0.45, 0.55),
	},
	"Sympathetic Arousal": {
		"gsr": (0.50, 0.70),
		"spo2": (0.33, 0.60),
		"temp": (0.35, 0.50),
		"accel": (0.50, 0.75),
	},
	"Parasympathetic Suppression": {
		"gsr": (0.05, 0.20),
		"spo2": (0.00, 0.33),
		"temp": (0.27, 0.36),
		"accel": (0.45, 0.55),
	},
	"Mixed Dysregulation": {
		"gsr": (0.45, 0.68),
		"spo2": (0.20, 0.60),
		"temp": (0.38, 0.55),
		"accel": (0.60, 1.00),
	},
}

NOISE_SIGMA = 0.025


def _sample_channel(low: float, high: float, n_samples: int) -> np.ndarray:
	base = np.random.uniform(low, high, size=n_samples).astype(np.float32)
	noise = np.random.normal(0.0, NOISE_SIGMA, size=n_samples).astype(np.float32)
	return np.clip(base + noise, 0.0, 1.0)


def generate_window(class_name: str, n_samples: int) -> np.ndarray:
	ranges = CLASS_RANGES[class_name]
	window = np.zeros((n_samples, 4), dtype=np.float32)
	window[:, 0] = _sample_channel(*ranges["gsr"], n_samples)
	window[:, 1] = _sample_channel(*ranges["spo2"], n_samples)
	window[:, 2] = _sample_channel(*ranges["temp"], n_samples)
	window[:, 3] = _sample_channel(*ranges["accel"], n_samples)
	return window


def generate_dataset(
	windows_per_class: int = 1000,
	n_samples: int = 30,
) -> Tuple[np.ndarray, np.ndarray]:
	x_data = []
	y_data = []

	for class_idx, class_name in enumerate(CLASSES):
		for _ in range(windows_per_class):
			x_data.append(generate_window(class_name=class_name, n_samples=n_samples))
			y_data.append(class_idx)

	x = np.asarray(x_data, dtype=np.float32)
	y_idx = np.asarray(y_data, dtype=np.int32)

	# Shuffle before splitting so each class is represented in train/validation.
	perm = np.random.permutation(len(y_idx))
	x = x[perm]
	y_idx = y_idx[perm]

	y = tf.keras.utils.to_categorical(y_idx, num_classes=len(CLASSES))
	return x, y


def main() -> None:
	np.random.seed(42)
	tf.random.set_seed(42)

	print("Generating hardware-matched dataset...")
	x, y = generate_dataset(windows_per_class=1000, n_samples=30)
	print(f"Dataset shape: X={x.shape}, y={y.shape}")

	model = build_model()
	model.compile(
		optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
		loss="categorical_crossentropy",
		metrics=["accuracy"],
	)

	callbacks = [
		tf.keras.callbacks.EarlyStopping(
			monitor="val_accuracy",
			patience=5,
			restore_best_weights=True,
		),
		tf.keras.callbacks.ReduceLROnPlateau(
			monitor="val_loss",
			factor=0.5,
			patience=2,
			min_lr=1e-5,
		),
	]

	print("Training model (up to 30 epochs with early stopping)...")
	model.fit(
		x,
		y,
		epochs=30,
		batch_size=32,
		validation_split=0.2,
		shuffle=True,
		callbacks=callbacks,
		verbose=1,
	)

	probs = model(x, training=False)
	pred_labels = np.argmax(probs.numpy(), axis=1)
	true_labels = np.argmax(y, axis=1)
	acc = float(np.mean(pred_labels == true_labels))
	save_path = os.path.join(CURRENT_DIR, "saved", "ans_model.h5")
	weights_save_path = os.path.join(CURRENT_DIR, "saved", "ans_model.weights.h5")
	os.makedirs(os.path.dirname(save_path), exist_ok=True)
	model.save(save_path)
	model.save_weights(weights_save_path)

	print(f"Final accuracy: {acc * 100:.2f}%")
	print(f"Model saved to: {save_path}")
	print(f"Weights saved to: {weights_save_path}")


if __name__ == "__main__":
	main()
