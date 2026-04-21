"""Model utilities for ANS state classification."""

from __future__ import annotations

import os
import pickle
from typing import Dict, List, Tuple, Union

import numpy as np

try:
	import tensorflow as tf
	from tensorflow.keras import layers
	TF_AVAILABLE = True
except ImportError:
	TF_AVAILABLE = False
	tf = None
	layers = None


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
MODEL_WINDOW_SAMPLES = 30


class SimpleModel:
	"""Wrapper for simple k-NN classifier to match ANSClassifier interface."""
	
	def __init__(self, class_means: np.ndarray, ranges: Dict = None):
		self.class_means = class_means  # Shape: (4, 30, 4)
		self.ranges = ranges or {}
		self.is_simple = True
	
	def forward_with_cav(self, inputs, training: bool = False, mc_dropout: bool = False):
		"""Return (probs, cav) to match ANSClassifier interface."""
		# inputs shape: (batch_size, 30, 4)
		if inputs.shape[0] != 1:
			raise ValueError("SimpleModel expects batch_size=1")
		
		window = inputs[0]  # (30, 4)
		window_mean = np.mean(window, axis=0)  # (4,)
		
		# Compute distances to each class mean
		distances = []
		for class_idx in range(len(CLASSES)):
			class_mean = np.mean(self.class_means[class_idx], axis=0)  # (4,)
			dist = np.linalg.norm(window_mean - class_mean)
			distances.append(dist)
		
		distances = np.array(distances)
		# Convert distances to similarity (inverse)
		max_dist = np.max(distances) + 1e-8
		similarities = 1.0 / (1.0 + distances / max_dist)
		probs = similarities / np.sum(similarities)  # Normalize to [0,1]
		
		# Compute CAV based on channel-wise variance
		cav = np.var(window, axis=0)  # (4,)
		cav = cav / (np.sum(cav) + 1e-8)  # Normalize
		
		return probs, cav
	
	def extract_features(self, inputs, training: bool = False):
		"""Return (bilstm_hidden, pcs_state, cav) to match ANSClassifier interface."""
		if inputs.shape[0] != 1:
			raise ValueError("SimpleModel expects batch_size=1")
		
		window = inputs[0]  # (30, 4)
		window_flat = window.reshape(-1)  # Flatten to (120,)
		
		# Compute CAV
		cav = np.var(window, axis=0)  # (4,)
		cav = cav / (np.sum(cav) + 1e-8)
		
		# Mock embedding for PCS computation
		bilstm_hidden = window_flat[:128] if len(window_flat) >= 128 else np.pad(window_flat, (0, 128 - len(window_flat)))
		pcs_state = np.tile(bilstm_hidden, 1)  # Repeat for 4 channels
		
		return bilstm_hidden, pcs_state, cav


if TF_AVAILABLE:
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
	if TF_AVAILABLE:
		model = ANSClassifier(name="ans_classifier")
		_ = model(tf.zeros((1, MODEL_WINDOW_SAMPLES, 4), dtype=tf.float32), training=False)
		return model
	else:
		raise RuntimeError("TensorFlow is not available. Cannot build TensorFlow model.")


def _model_path() -> str:
	return os.path.join(os.path.dirname(__file__), "saved", "ans_model.h5")


def _weights_path() -> str:
	return os.path.join(os.path.dirname(__file__), "saved", "ans_model.weights.h5")


def _simple_model_path() -> str:
	return os.path.join(os.path.dirname(__file__), "saved", "ans_model_simple.pkl")


def load_or_create_model() -> Union[ANSClassifier, SimpleModel]:
	os.makedirs(os.path.dirname(_model_path()), exist_ok=True)
	
	# Try loading the simple pickle model first (new trained model)
	simple_model_path = _simple_model_path()
	if os.path.exists(simple_model_path):
		try:
			with open(simple_model_path, 'rb') as f:
				model_data = pickle.load(f)
			simple_model = SimpleModel(
				class_means=model_data.get('class_means'),
				ranges=model_data.get('ranges')
			)
			return simple_model
		except Exception as e:
			print(f"Failed to load simple model: {e}")
	
	# Fallback to TensorFlow model
	if TF_AVAILABLE:
		path = _model_path()
		weights_path = _weights_path()

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

		x_dummy = np.random.rand(10, MODEL_WINDOW_SAMPLES, 4).astype(np.float32)
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
	else:
		raise RuntimeError("TensorFlow not available and no pickle model found. Cannot load model.")


def _round_and_renormalize(weights: np.ndarray) -> Dict[str, float]:
	rounded = np.round(weights, 2)
	diff = round(1.0 - float(np.sum(rounded)), 2)
	if abs(diff) > 0 and rounded.size > 0:
		rounded[int(np.argmax(rounded))] = round(rounded[int(np.argmax(rounded))] + diff, 2)
	return {name: float(val) for name, val in zip(SENSOR_NAMES, rounded.tolist())}


def mc_dropout_predict(model: Union[ANSClassifier, SimpleModel], window: np.ndarray, T: int = 20) -> Dict[str, object]:
	if window.shape != (MODEL_WINDOW_SAMPLES, 4):
		raise ValueError(
			f"Expected window shape ({MODEL_WINDOW_SAMPLES}, 4), got {window.shape}"
		)

	batch = np.expand_dims(window.astype(np.float32), axis=0)
	probs_samples = []
	cav_samples = []

	# Handle SimpleModel differently (no MC-dropout, just single forward pass)
	if isinstance(model, SimpleModel):
		probs, cav = model.forward_with_cav(batch, training=False, mc_dropout=False)
		# probs and cav are already numpy arrays, don't call .numpy()
		probs = np.asarray(probs)
		cav = np.asarray(cav)
		# Repeat for T iterations to simulate uncertainty
		probs_samples = [probs for _ in range(T)]
		cav_samples = [cav for _ in range(T)]
	else:
		# TensorFlow model with MC-dropout
		for _ in range(T):
			probs, cav = model.forward_with_cav(batch, training=False, mc_dropout=True)
			# Handle both TensorFlow tensors and numpy arrays
			if hasattr(probs, 'numpy'):
				probs_samples.append(probs.numpy()[0])
			else:
				probs_samples.append(np.asarray(probs)[0])
			
			if hasattr(cav, 'numpy'):
				cav_samples.append(cav.numpy()[0])
			else:
				cav_samples.append(np.asarray(cav)[0])

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


def compute_pcs(model: Union[ANSClassifier, SimpleModel], window: np.ndarray) -> Tuple[float, bool]:
	if window.shape != (MODEL_WINDOW_SAMPLES, 4):
		raise ValueError(
			f"Expected window shape ({MODEL_WINDOW_SAMPLES}, 4), got {window.shape}"
		)

	batch = np.expand_dims(window.astype(np.float32), axis=0)
	
	if isinstance(model, SimpleModel):
		# For simple model, use a simplified PCS calculation
		bilstm_hidden, _, cav = model.extract_features(batch, training=False)
		slices = np.split(bilstm_hidden, 4)
		cav_vals = cav
	else:
		# For TensorFlow model
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
