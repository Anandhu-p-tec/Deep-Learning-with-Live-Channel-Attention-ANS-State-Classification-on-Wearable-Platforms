"""Simple ANS classifier training using just NumPy - no TensorFlow dependency."""

import numpy as np
import os
import pickle

# Class ranges based on user's sensor data pattern
CLASS_RANGES = {
    "Normal Baseline": {
        # Pre-contact baseline (no finger on sensor)
        "gsr": (0.00, 0.50),
        "spo2": (0.00, 0.25),
        "temp": (0.20, 0.35),
        "accel": (0.00, 0.05),
    },
    "Sympathetic Arousal": {
        # Post-contact stressed state (finger on sensor, during contact)
        "gsr": (0.30, 0.70),
        "spo2": (0.20, 0.40),
        "temp": (0.20, 0.40),
        "accel": (0.00, 0.10),
    },
    "Parasympathetic Suppression": {
        # Low arousal, high vagal tone
        "gsr": (0.05, 0.25),
        "spo2": (0.00, 0.20),
        "temp": (0.18, 0.32),
        "accel": (0.00, 0.08),
    },
    "Mixed Dysregulation": {
        # High stress, dysregulated response
        "gsr": (0.50, 1.00),
        "spo2": (0.25, 0.50),
        "temp": (0.32, 0.48),
        "accel": (0.08, 0.35),
    },
}

CLASSES = list(CLASS_RANGES.keys())
NOISE_SIGMA = 0.025


def _sample_channel(low, high, n_samples):
    """Sample from uniform distribution with added Gaussian noise."""
    base = np.random.uniform(low, high, size=n_samples).astype(np.float32)
    noise = np.random.normal(0.0, NOISE_SIGMA, size=n_samples).astype(np.float32)
    return np.clip(base + noise, 0.0, 1.0)


def generate_window(class_name, n_samples=30):
    """Generate a single window of synthetic data for a class."""
    ranges = CLASS_RANGES[class_name]
    window = np.zeros((n_samples, 4), dtype=np.float32)
    window[:, 0] = _sample_channel(*ranges["gsr"], n_samples)
    window[:, 1] = _sample_channel(*ranges["spo2"], n_samples)
    window[:, 2] = _sample_channel(*ranges["temp"], n_samples)
    window[:, 3] = _sample_channel(*ranges["accel"], n_samples)
    return window


def generate_dataset(windows_per_class=1000, n_samples=30):
    """Generate training dataset with synthetic data from class ranges."""
    x_data = []
    y_data = []
    
    for class_idx, class_name in enumerate(CLASSES):
        for _ in range(windows_per_class):
            x_data.append(generate_window(class_name=class_name, n_samples=n_samples))
            y_data.append(class_idx)
    
    x = np.asarray(x_data, dtype=np.float32)
    y = np.asarray(y_data, dtype=np.int32)
    
    # Shuffle
    perm = np.random.permutation(len(y))
    x = x[perm]
    y = y[perm]
    
    return x, y


def simple_classifier(X_train, y_train, n_epochs=10):
    """Simple nearest-neighbor based classifier using mean of each class."""
    # Compute mean for each class
    class_means = {}
    for class_idx in range(len(CLASSES)):
        class_data = X_train[y_train == class_idx]
        # Average the windows to get a single representative vector
        class_means[class_idx] = np.mean(class_data, axis=(0, 1))  # Average over windows and samples
    
    return class_means


def predict(X, class_means):
    """Predict class for each window using nearest mean."""
    predictions = []
    for window in X:
        # Average the window to get a single vector
        window_mean = np.mean(window, axis=0)
        
        # Find nearest class mean
        distances = []
        for class_idx in range(len(CLASSES)):
            dist = np.linalg.norm(window_mean - class_means[class_idx])
            distances.append(dist)
        
        pred = np.argmin(distances)
        predictions.append(pred)
    
    return np.array(predictions)


def main():
    """Train and save the model."""
    np.random.seed(42)
    
    print("Generating synthetic training dataset...")
    X, y = generate_dataset(windows_per_class=100, n_samples=30)
    print(f"Dataset shape: X={X.shape}, y={y.shape}")
    print(f"Classes: {CLASSES}")
    
    # 80-20 split
    split_idx = int(0.8 * len(X))
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]
    
    print(f"Training set: {X_train.shape}")
    print(f"Validation set: {X_val.shape}")
    
    print("\nTraining classifier...")
    class_means = simple_classifier(X_train, y_train)
    
    # Evaluate on training set
    train_pred = predict(X_train, class_means)
    train_acc = np.mean(train_pred == y_train)
    print(f"Training accuracy: {train_acc:.2%}")
    
    # Evaluate on validation set
    val_pred = predict(X_val, class_means)
    val_acc = np.mean(val_pred == y_val)
    print(f"Validation accuracy: {val_acc:.2%}")
    
    # Save class means and class names
    output_dir = os.path.join(os.path.dirname(__file__), "saved")
    os.makedirs(output_dir, exist_ok=True)
    
    model_data = {
        "class_means": class_means,
        "classes": CLASSES,
        "ranges": CLASS_RANGES,
    }
    
    model_path = os.path.join(output_dir, "ans_model_simple.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model_data, f)
    
    print(f"\nModel saved to: {model_path}")
    print("Training complete!")


if __name__ == "__main__":
    main()
