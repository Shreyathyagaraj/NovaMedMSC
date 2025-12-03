import pandas as pd
import xgboost as xgb
import pickle
from sklearn.model_selection import train_test_split

# Load dataset
df = pd.read_csv("patients.csv")

# Convert date/time
df["date"] = pd.to_datetime(df["RegistrationDate"], errors="coerce")
df["hour"] = pd.to_datetime(df["RegistrationTime"], format="%H:%M:%S", errors="coerce").dt.hour
df = df.dropna(subset=["date", "hour", "department"])

df["weekday"] = df["date"].dt.weekday  # 0=Mon, 6=Sun

# Encode departments numerically
df["dept_code"] = df["department"].astype("category").cat.codes

# Group by weekday, hour, department
counts = df.groupby(["weekday", "hour", "dept_code"]).size().reset_index(name="count")

X = counts[["weekday", "hour", "dept_code"]]
y = counts["count"]

# Split & train model
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = xgb.XGBRegressor(objective="reg:squarederror", n_estimators=200, max_depth=5)
model.fit(X_train, y_train)

# Save model and department mapping
with open("xgb_patient_model.pkl", "wb") as f:
    pickle.dump(model, f)

dept_map = dict(enumerate(df["department"].astype("category").cat.categories))
with open("department_mapping.pkl", "wb") as f:
    pickle.dump(dept_map, f)

print("✅ Model trained and saved (xgb_patient_model.pkl + department_mapping.pkl)")
