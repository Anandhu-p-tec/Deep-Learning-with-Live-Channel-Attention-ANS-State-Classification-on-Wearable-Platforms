import re
from collections import Counter

log_data = """
18:08:03 INFO [SERIAL] GSR=2750 | SPO2=0.0 | TEMP=36.6°C | ECG=638 | STATE=SYMP_AROUSAL
18:08:04 INFO [SERIAL] GSR=2754 | SPO2=0.0 | TEMP=36.2°C | ECG=755 | STATE=SYMP_AROUSAL
18:08:07 INFO [SERIAL] GSR=2823 | SPO2=0.0 | TEMP=36.1°C | ECG=2756 | STATE=SYMP_AROUSAL
18:08:07 INFO [SERIAL] GSR=1152 | SPO2=0.0 | TEMP=36.1°C | ECG=2583 | STATE=MILD
18:08:05 INFO [SERIAL] GSR=0 | SPO2=0.0 | TEMP=36.9°C | ECG=2584 | STATE=MILD
18:08:10 INFO [SERIAL] GSR=0 | SPO2=91.0 | TEMP=36.9°C | ECG=2754 | STATE=SYMP_AROUSAL
18:08:12 INFO [SERIAL] GSR=2748 | SPO2=91.1 | TEMP=36.8°C | ECG=2752 | STATE=PARA_SUPP
18:08:12 INFO [SERIAL] GSR=0 | SPO2=90.3 | TEMP=36.3°C | ECG=2755 | STATE=SYMP_AROUSAL
18:08:14 INFO [SERIAL] GSR=2313 | SPO2=90.4 | TEMP=36.3°C | ECG=2710 | STATE=PARA_SUPP
18:08:15 INFO [SERIAL] GSR=0 | SPO2=90.5 | TEMP=36.7°C | ECG=2708 | STATE=SYMP_AROUSAL
18:08:16 INFO [SERIAL] GSR=16 | SPO2=90.2 | TEMP=36.7°C | ECG=2754 | STATE=SYMP_AROUSAL
18:08:18 INFO [SERIAL] GSR=0 | SPO2=90.5 | TEMP=36.6°C | ECG=2700 | STATE=SYMP_AROUSAL
18:08:19 INFO [SERIAL] GSR=1647 | SPO2=90.5 | TEMP=36.3°C | ECG=2680 | STATE=SYMP_AROUSAL
18:08:20 INFO [SERIAL] GSR=0 | SPO2=91.9 | TEMP=36.3°C | ECG=2695 | STATE=SYMP_AROUSAL
18:08:21 INFO [SERIAL] GSR=2737 | SPO2=0.0 | TEMP=36.2 | ECG=2713 | STATE=MILD
18:08:21 INFO [SERIAL] GSR=0 | SPO2=0.0 | TEMP=36.2°C | ECG=1944 | STATE=MILD
18:08:21 INFO [SERIAL] GSR=2607 | SPO2=0.0 | TEMP=36.2 | ECG=2661 | STATE=SYMP_AROUSAL
18:08:22 INFO [SERIAL] GSR=2739 | SPO2=0.0 | TEMP=36.2 | ECG=2660 | STATE=SYMP_AROUSAL
18:08:22 INFO [SERIAL] GSR=1339 | SPO2=0.0 | TEMP=36.2°C | ECG=2661 | STATE=MILD
18:08:23 INFO [SERIAL] GSR=0 | SPO2=0.0 | TEMP=36.7 | ECG=2584 | STATE=MILD
18:08:23 INFO [SERIAL] GSR=69 | SPO2=0.0 | TEMP=36.7 | ECG=2660 | STATE=MILD
18:08:24 INFO [SERIAL] GSR=2752 | SPO2=0.0 | TEMP=36.7°C | ECG=2660 | STATE=SYMP_AROUSAL
18:08:24 INFO [SERIAL] GSR=1203 | SPO2=0.0 | TEMP=36.7°C | ECG=2574 | STATE=MILD
18:08:26 INFO [SERIAL] GSR=0 | SPO2=0.0 | TEMP=36.9°C | ECG=1835 | STATE=MILD
18:08:26 INFO [SERIAL] GSR=2751 | SPO2=0.0 | TEMP=36.9°C | ECG=1642 | STATE=SYMP_AROUSAL
18:08:28 INFO [SERIAL] GSR=835 | SPO2=0.0 | TEMP=36.9°C | ECG=1314 | STATE=MILD
18:08:29 INFO [SERIAL] GSR=0 | SPO2=0.0 | TEMP=36.7°C | ECG=730 | STATE=MILD
18:08:31 INFO [SERIAL] GSR=2743 | SPO2=0.0 | TEMP=36.7°C | ECG=1132 | STATE=SYMP_AROUSAL
18:08:31 INFO [SERIAL] GSR=2742 | SPO2=0.0 | TEMP=36.3°C | ECG=1022 | STATE=SYMP_AROUSAL
"""

# Parse the data
gsr_values = []
spo2_values = []
temp_values = []
state_values = []

for line in log_data.strip().split('\n'):
    if '[SERIAL]' in line:
        # Extract GSR
        gsr_match = re.search(r'GSR=(\d+)', line)
        if gsr_match:
            gsr_values.append(int(gsr_match.group(1)))
        
        # Extract SPO2
        spo2_match = re.search(r'SPO2=([\d.]+)', line)
        if spo2_match:
            spo2_values.append(float(spo2_match.group(1)))
        
        # Extract TEMP
        temp_match = re.search(r'TEMP=([\d.]+)', line)
        if temp_match:
            temp_values.append(float(temp_match.group(1)))
        
        # Extract STATE
        state_match = re.search(r'STATE=(\w+)', line)
        if state_match:
            state_values.append(state_match.group(1))

# Calculate most common values
gsr_counter = Counter(gsr_values)
spo2_counter = Counter(spo2_values)
temp_counter = Counter(temp_values)
state_counter = Counter(state_values)

print("=" * 80)
print("📊 SENSOR DATA FREQUENCY ANALYSIS")
print("=" * 80)
print()

print("🔴 GSR (Galvanic Skin Response)")
print("-" * 80)
print(f"Total readings: {len(gsr_values)}")
print(f"Most common value: {gsr_counter.most_common(1)[0][0]} (appears {gsr_counter.most_common(1)[0][1]} times)")
print("\nTop 5 most frequent GSR values:")
for value, count in gsr_counter.most_common(5):
    print(f"  • {value:5d} → {count:2d}x")

print("\n🫁 SPO2 (Blood Oxygen Saturation %)")
print("-" * 80)
print(f"Total readings: {len(spo2_values)}")
print(f"Most common value: {spo2_counter.most_common(1)[0][0]}% (appears {spo2_counter.most_common(1)[0][1]} times)")
print("\nTop 5 most frequent SPO2 values:")
for value, count in spo2_counter.most_common(5):
    print(f"  • {value:5.1f}% → {count:2d}x")

print("\n🌡️  TEMP (Body Temperature °C)")
print("-" * 80)
print(f"Total readings: {len(temp_values)}")
print(f"Most common value: {temp_counter.most_common(1)[0][0]}°C (appears {temp_counter.most_common(1)[0][1]} times)")
print("\nTop 5 most frequent TEMP values:")
for value, count in temp_counter.most_common(5):
    print(f"  • {value:5.1f}°C → {count:2d}x")

print("\n🧠 STATE (ANS Classification)")
print("-" * 80)
print(f"Total readings: {len(state_values)}")
print(f"Most common state: {state_counter.most_common(1)[0][0]} (appears {state_counter.most_common(1)[0][1]} times)")
print("\nAll states breakdown:")
for value, count in state_counter.most_common():
    percentage = (count / len(state_values)) * 100
    print(f"  • {value:20s} → {count:2d}x ({percentage:5.1f}%)")

print("\n" + "=" * 80)
print("📈 KEY INSIGHTS")
print("=" * 80)

# Analyze when sensors are active
active_gsr = [v for v in gsr_values if v > 500]
active_spo2 = [v for v in spo2_values if v > 0]

print(f"\n✅ GSR Active (>500):   {len(active_gsr):2d}x / {len(gsr_values):2d} ({len(active_gsr)/len(gsr_values)*100:5.1f}%)")
print(f"✅ SPO2 Active (>0):   {len(active_spo2):2d}x / {len(spo2_values):2d} ({len(active_spo2)/len(spo2_values)*100:5.1f}%)")
print(f"✅ TEMP Range:         {min(temp_values):.1f}°C - {max(temp_values):.1f}°C (Δ {max(temp_values)-min(temp_values):.1f}°C)")

if active_gsr:
    print(f"\n🔴 GSR when active (>500):")
    print(f"   Most common: {Counter(active_gsr).most_common(1)[0][0]}")
    print(f"   Range: {min(active_gsr)} - {max(active_gsr)}")

if active_spo2:
    print(f"\n🫁 SPO2 when active (>0):")
    print(f"   Most common: {Counter(active_spo2).most_common(1)[0][0]}%")
    print(f"   Range: {min(active_spo2):.1f}% - {max(active_spo2):.1f}%")

print("\n" + "=" * 80)
