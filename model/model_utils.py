"""Model utilities for ANS state classification."""

from __future__ import annotations

import os
from typing import Dict, List, Tuple

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers


CLASSES = [
	"Normal Baseline",
	"Sympathetic Arousal",
	"Parasympathetic Suppression",
	"Mixed Dysregulation",
]

CLASS_COLORS = {
	"Normal Baseline": "#1D9E75",
	"Sympathetic Arousal": "#D85A30",
	"Parasympathetic Suppression": "#378ADD",
	"Mixed Dysregulation": "#9B59B6",
}

SENSOR_NAMES = ["GSR", "SpO2", "Temp", "Accel"]


@tf.keras.utils.register_keras_serializable()
class ANSClassifier(tf.keras.Model):
	"""Conv + BiLSTM model with channel-attention vector (CAV)."""

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.conv1 = layers.Conv1D(32, kernel_size=5, activation="relu", padding="same")
		self.bn1 = layers.BatchNormalization()
		self.pool1 = layers.MaxPooling1D(pool_size=2)

		self.conv2 = layers.Conv1D(64, kernel_size=3, activation="relu", padding="same")
		self.bn2 = layers.BatchNormalization()
		self.pool2 = layers.MaxPooling1D(pool_size=2)

		self.gap = layers.GlobalAveragePooling1D()
		self.cav_dense = layers.Dense(4, use_bias=False)
		self.cav_softmax = layers.Softmax(name="cav")

		self.bilstm = layers.Bidirectional(layers.LSTM(32), name="bilstm")
		self.dropout = layers.Dropout(0.4)
		self.dense1 = layers.Dense(32, activation="relu")
		self.out_dense = layers.Dense(4, activation="softmax", name="class_probs")

		# 128-d embedding derived from BiLSTM output for PCS computation.
		self.pcs_projection = layers.Dense(128, name="pcs_projection")

	def get_config(self):
		return {}

	@classmethod
	def from_config(cls, config):
		return cls(**config)

	def extract_features(self, inputs, training: bool = False):
		x = self.conv1(inputs)
		x = self.bn1(x, training=training)
		x = self.pool1(x)

		x = self.conv2(x)
		x = self.bn2(x, training=training)
		x = self.pool2(x)

		gap = self.gap(x)
		cav_logits = self.cav_dense(gap)
		cav = self.cav_softmax(cav_logits)

		channel_mean = tf.reduce_mean(inputs, axis=1)
		weighted_channel_mean = channel_mean * cav
		weighted_input = inputs * tf.expand_dims(weighted_channel_mean, axis=1)
		bilstm_hidden = self.bilstm(weighted_input, training=training)
		pcs_state = self.pcs_projection(bilstm_hidden)
		return bilstm_hidden, pcs_state, cav

	def forward_with_cav(self, inputs, training: bool = False, mc_dropout: bool = False):
		# For MC-dropout inference, keep BatchNorm/statistical layers in inference
		# mode and activate only dropout for stochastic uncertainty sampling.
		bilstm_hidden, _, cav = self.extract_features(inputs, training=training)
		dropout_active = bool(training or mc_dropout)
		x = self.dropout(bilstm_hidden, training=dropout_active)
		x = self.dense1(x)
		probs = self.out_dense(x)
		return probs, cav

	def call(self, inputs, training: bool = False):
		probs, _ = self.forward_with_cav(inputs, training=training, mc_dropout=False)
		return probs


def build_model() -> ANSClassifier:
	model = ANSClassifier(name="ans_classifier")
	_ = model(tf.zeros((1, 500, 4), dtype=tf.float32), training=False)
	return model


def _model_path() -> str:
	return os.path.join(os.path.dirname(__file__), "saved", "ans_model.h5")


def _weights_path() -> str:
	return os.path.join(os.path.dirname(__file__), "saved", "ans_model.weights.h5")


def load_or_create_model() -> ANSClassifier:
	path = _model_path()
	weights_path = _weights_path()
	os.makedirs(os.path.dirname(path), exist_ok=True)

	model = build_model()

	if os.path.exists(weights_path):
		try:
			model.load_weights(weights_path)
			return model
		except Exception:
			pass

	if os.path.exists(path):
		try:
			loaded = tf.keras.models.load_model(
				path,
				custom_objects={"ANSClassifier": ANSClassifier},
				compile=False,
			)
			return loaded
		except Exception:
			pass

	x_dummy = np.random.rand(10, 500, 4).astype(np.float32)
	y_idx = np.random.randint(0, len(CLASSES), size=(10,))
	y_dummy = tf.keras.utils.to_categorical(y_idx, num_classes=len(CLASSES))

	model.compile(
		optimizer="adam",
		loss="categorical_crossentropy",
		metrics=["accuracy"],
	)
	model.fit(x_dummy, y_dummy, epochs=1, batch_size=2, verbose=0)
	model.save(path)
	model.save_weights(weights_path)
	return model


def _round_and_renormalize(weights: np.ndarray) -> Dict[str, float]:
	rounded = np.round(weights, 2)
	diff = round(1.0 - float(np.sum(rounded)), 2)
	if abs(diff) > 0 and rounded.size > 0:
		rounded[int(np.argmax(rounded))] = round(rounded[int(np.argmax(rounded))] + diff, 2)
	return {name: float(val) for name, val in zip(SENSOR_NAMES, rounded.tolist())}


def mc_dropout_predict(model: ANSClassifier, window: np.ndarray, T: int = 20) -> Dict[str, object]:
	if window.shape != (500, 4):
		raise ValueError(f"Expected window shape (500, 4), got {window.shape}")

	batch = np.expand_dims(window.astype(np.float32), axis=0)
	probs_samples = []
	cav_samples = []

	for _ in range(T):
		probs, cav = model.forward_with_cav(batch, training=False, mc_dropout=True)
		probs_samples.append(probs.numpy()[0])
		cav_samples.append(cav.numpy()[0])

	probs_samples = np.asarray(probs_samples)
	cav_samples = np.asarray(cav_samples)

	mean_probs = np.mean(probs_samples, axis=0)
	mean_cav = np.mean(cav_samples, axis=0)
	mean_cav = mean_cav / max(float(np.sum(mean_cav)), 1e-8)

	variance = float(np.mean(np.var(probs_samples, axis=0)))
	pred_idx = int(np.argmax(mean_probs))
	cav_dict = _round_and_renormalize(mean_cav)
	dominant_sensor = max(cav_dict, key=cav_dict.get)

	return {
		"predicted_class": CLASSES[pred_idx],
		"confidence": round(float(np.max(mean_probs) * 100.0), 1),
		"variance": round(variance, 4),
		"low_confidence": bool(variance > 0.12),
		"cav": cav_dict,
		"dominant_sensor": dominant_sensor,
		"all_probs": {
			class_name: round(float(prob), 4)
			for class_name, prob in zip(CLASSES, mean_probs.tolist())
		},
	}


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
	denom = (np.linalg.norm(a) * np.linalg.norm(b))
	if denom <= 1e-8:
		return 0.0
	return float(np.dot(a, b) / denom)


def compute_pcs(model: ANSClassifier, window: np.ndarray) -> Tuple[float, bool]:
	if window.shape != (500, 4):
		raise ValueError(f"Expected window shape (500, 4), got {window.shape}")

	batch = np.expand_dims(window.astype(np.float32), axis=0)
	_, pcs_state, cav = model.extract_features(batch, training=False)

	hidden = pcs_state.numpy()[0]  # (128,)
	slices = np.split(hidden, 4)

	cav_vals = cav.numpy()[0]
	sorted_idx = np.argsort(cav_vals)[::-1]
	dominant_idx, secondary_idx = int(sorted_idx[0]), int(sorted_idx[1])

	pcs = _cosine_similarity(slices[dominant_idx], slices[secondary_idx])
	pcs = round(pcs, 2)
	sensor_conflict = pcs < 0.30
	return pcs, sensor_conflict


def get_dominant_channel_info(cav_dict: Dict[str, float]) -> List[Tuple[str, float]]:
	return sorted(cav_dict.items(), key=lambda x: x[1], reverse=True)
