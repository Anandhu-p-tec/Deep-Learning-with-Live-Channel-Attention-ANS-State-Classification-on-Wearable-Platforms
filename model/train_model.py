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
	windows_per_class: int = 310,
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
	y = tf.keras.utils.to_categorical(np.asarray(y_data), num_classes=len(CLASSES))
	return x, y


def main() -> None:
	np.random.seed(42)
	tf.random.set_seed(42)

	print("Generating synthetic dataset (1240 windows)...")
	x, y = generate_dataset(windows_per_class=310, n_samples=500)
	print(f"Dataset shape: X={x.shape}, y={y.shape}")

	model = build_model()
	model.compile(
		optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
		loss="categorical_crossentropy",
		metrics=["accuracy"],
	)

	print("Training model for 5 epochs...")
	model.fit(
		x,
		y,
		epochs=5,
		batch_size=32,
		validation_split=0.2,
		verbose=1,
	)

	probs, _ = model(x, training=False)
	pred_labels = np.argmax(probs.numpy(), axis=1)
	true_labels = np.argmax(y, axis=1)
	acc = float(np.mean(pred_labels == true_labels))
	save_path = os.path.join(CURRENT_DIR, "saved", "ans_model.h5")
	os.makedirs(os.path.dirname(save_path), exist_ok=True)
	model.save(save_path)

	print(f"Final accuracy: {acc * 100:.2f}%")
	print(f"Model saved to: {save_path}")


if __name__ == "__main__":
	main()
