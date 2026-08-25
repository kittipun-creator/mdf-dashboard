import google.generativeai as genai

print("กำลังเชื่อมต่อกับ Google AI...")
genai.configure(api_key="AQ.Ab8RN6IPdhVSTM6FBXjshPIRRDl-kS7XjNuGy4sZ6xFi9PVDTQ")

try:
    models = list(genai.list_models())
    print(f"✅ เจอโมเดลทั้งหมด: {len(models)} ตัว")
    for m in models:
        print("👉", m.name)
except Exception as e:
    print("❌ เกิด Error ข้อความว่า:", e)

    