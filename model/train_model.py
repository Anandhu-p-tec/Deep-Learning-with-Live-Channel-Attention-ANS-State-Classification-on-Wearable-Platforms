"""Train ANS classifier on synthetic data."""

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

from serial_reader.simulator import get_simulated_window
from model.model_utils import CLASSES, build_model


MODE_BY_CLASS = {
	0: "normal_baseline",
	1: "sympathetic_arousal",
	2: "parasympathetic_suppression",
	3: "mixed_dysregulation",
}


def generate_dataset(
	windows_per_class: int = 600,
	n_samples: int = 500,
) -> Tuple[np.ndarray, np.ndarray]:
	x_data = []
	y_data = []

	for class_idx in range(len(CLASSES)):
		mode = MODE_BY_CLASS[class_idx]
		for _ in range(windows_per_class):
			x_data.append(get_simulated_window(mode=mode, n_samples=n_samples))
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

	print("Generating synthetic dataset...")
	x, y = generate_dataset(windows_per_class=600, n_samples=500)
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
			patience=4,
			restore_best_weights=True,
		),
		tf.keras.callbacks.ReduceLROnPlateau(
			monitor="val_loss",
			factor=0.5,
			patience=2,
			min_lr=1e-5,
		),
	]

	print("Training model (up to 20 epochs with early stopping)...")
	model.fit(
		x,
		y,
		epochs=20,
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
