import google.generativeai as genai

# Your actual API key
genai.configure(api_key="AIzaSyDpiQzAeAG0oXyZIsXIw7wTfRNI_mbj9GM")

print("Uploading Player Rules. This might take a second...")
player_rules = genai.upload_file("PlayerDnDBasicRules_v0.2.pdf")

print("Uploading DM Rules...")
dm_rules = genai.upload_file("DMBasicRulesv.0.3.pdf")

print("\n--- GRAB THESE URIS ---")
print(f"Player URI: {player_rules.uri}")
print(f"DM URI: {dm_rules.uri}")
