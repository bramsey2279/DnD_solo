import os
import sys
import uuid
import json
import random
import re
import pydantic
from dotenv import load_dotenv
from flask import Flask, render_template_string, request, jsonify, send_from_directory

import google.generativeai as genai

# --- INITIALIZATION ---
load_dotenv()
app = Flask(__name__)

# --- SECURE CONFIG & PATHS ---
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("API Key missing. Check your .env file.")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(BASE_DIR, "core")
CHARS_PATH = os.path.join(BASE_DIR, "characters")
LOGS_PATH = os.path.join(BASE_DIR, "logs")
GEN_IMG_FOLDER = os.path.join(BASE_DIR, "images")
BOOK_PATH = os.path.join(LOGS_PATH, "campaign_log.txt")

for folder in [CORE_PATH, CHARS_PATH, LOGS_PATH, GEN_IMG_FOLDER]:
    os.makedirs(folder, exist_ok=True)

genai.configure(api_key=API_KEY)
image_engine = genai.GenerativeModel('gemini-2.5-flash-image')

# --- UTILITIES ---
def load_core_file(filename, default_content=""):
    filepath = os.path.join(CORE_PATH, filename)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    return default_content

def load_character_sheets():
    """Reads all JSON files in the characters folder so Mike knows our stats."""
    sheets = []
    if os.path.exists(CHARS_PATH):
        for f in os.listdir(CHARS_PATH):
            if f.endswith('.json'):
                with open(os.path.join(CHARS_PATH, f), 'r', encoding='utf-8') as jf:
                    sheets.append(jf.read())
    return "\n\n".join(sheets)

HTML_TEMPLATE = load_core_file("interface.html", default_content="<h1>HTML Template Missing</h1>")

# --- STRUCTURED OUTCOMES FOR THE DM ---
class CharacterUpdate(pydantic.BaseModel):
    character_name: str
    xp_change: int
    gold_change: int
    inventory_add: list[str]
    inventory_remove: list[str]

class DMResponseSchema(pydantic.BaseModel):
    narrative: str
    requires_roll: bool
    roll_type: str
    roll_reason: str
    generate_image: bool
    image_prompt: str
    roster_updates: list[CharacterUpdate]
    combat_active: bool
    whose_turn: str

# --- ROUTES ---
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/gallery')
def gallery():
    if os.path.exists(GEN_IMG_FOLDER):
        # Grab all the image files in the folder
        images = [f for f in os.listdir(GEN_IMG_FOLDER) if f.endswith(('.png', '.jpg', '.jpeg', '.gif'))]
        return jsonify(images)
    return jsonify([])

@app.route('/history')
def history():
    if os.path.exists(BOOK_PATH):
        with open(BOOK_PATH, 'r') as f: return f.read()[-100000:]
    return ""

@app.route('/gen_img/<filename>')
def serve_gen(filename):
    return send_from_directory(GEN_IMG_FOLDER, filename)

@app.route('/chat', methods=['POST'])
def chat():
    raw_in = request.form.get('msg', '').strip()
    
	# Translate asterisks into a highly restrictive command
    if raw_in == "***":
        u_in = "[SYSTEM: Auto-advancing initiative. Resolve EXACTLY ONE turn for the next entity in the order. DO NOT summarize multiple rounds or fast-forward. End your response immediately after their action.]"
    else:
        u_in = raw_in

    try:
        # 1. Load History
        history_context = ""
        if os.path.exists(BOOK_PATH):
            with open(BOOK_PATH, 'r', encoding='utf-8') as f: 
                file_size = os.path.getsize(BOOK_PATH)
                if file_size > 150000:
                    f.seek(file_size - 100000)
                history_context = f.read()

        final_responses = []

        # --- THE BANTER BYPASS ---
        # If you start your message with @@, it skips the DM entirely and only talks to the party.
        if u_in.startswith("@@"):
            clean_msg = u_in[2:].strip()
            user_block = f"Brandon (To Party): {clean_msg}\n"
            
            # Log it so we remember what you said
            with open(BOOK_PATH, 'a', encoding='utf-8') as f:
                f.write(user_block)
            history_context += user_block

            agents_to_run = ["Eric", "Lilly", "Lyra"]
            random.shuffle(agents_to_run) # Randomize who answers you first
            
            for agent_name in agents_to_run:
                persona_path = os.path.join(CHARS_PATH, f"{agent_name.lower()}_persona.txt")
                if os.path.exists(persona_path):
                    with open(persona_path, "r", encoding="utf-8") as f:
                        agent_instruction = f.read().strip()
                else:
                    agent_instruction = f"You are {agent_name}."

                agent_instruction += f"\nYou are taking a breather and bantering with the party. React directly to Brandon's last statement."
                
                agent_brain = genai.GenerativeModel(model_name='gemini-2.5-pro', system_instruction=agent_instruction)
                response = agent_brain.generate_content(f"Campaign History:\n{history_context}\n\nTask: Brandon just said something to the group. Banter back. Do not advance the plot.")
                reply = response.text
                
                final_responses.append(f"<b>{agent_name}:</b><br>{reply}")
                
                agent_block = f"{agent_name}: {reply}\n"
                with open(BOOK_PATH, 'a', encoding='utf-8') as f:
                    f.write(agent_block)
                history_context += agent_block
            
            return jsonify({
                "html": "<br><br>".join(final_responses),
                "whose_turn": "Brandon",
                "combat_active": False
            })

        # --- STANDARD DM ROUTE (If no @@ was used) ---
        char_data = load_character_sheets()
        
        dm_instruction = """
        You are the Dungeon Master (DM) named Mike for a brutal D&D campaign. Your players are Brandon, Eric, Lilly, and Lyra. 
        Narrate the environment, control NPCs, and decide the world's reactions based strictly on the provided Character Sheets. 
        Be vivid, immersive, and uncompromisingly ruthless, but fair. 
        
        CRITICAL COMBAT RULES: 
        1. Set 'combat_active' to true during fights. 
        2. Set 'whose_turn' to the exact name of the character who acts NEXT ("Brandon", "Eric", "Lilly", "Lyra", or "Monsters").
        3. NARRATE ONLY ONE TURN AT A TIME. Never summarize "Round 1", "Round 2", etc. Stop generating after the current entity finishes their action.
        
        If a player's action requires a stat check, saving throw, or combat attack, set 'requires_roll' to true and define the 'roll_type'. 
        If players earn experience points, find gold, or gain/lose items or hit points use the 'roster_updates' list.
        """
        dm_brain = genai.GenerativeModel(model_name='gemini-2.5-pro', system_instruction=dm_instruction)
         
        # --- PDF RULEBOOK INJECTION ---
        player_pdf = genai.get_file("files/m61uyxaidnit")
        dm_pdf = genai.get_file("files/ldjaknupk9sv")
        
        dm_prompt = [
            player_pdf,
            dm_pdf,
            f"Character Sheets:\n{char_data}\n\nHistory:\n{history_context}\n\nBrandon (Player Action): {u_in}\nProvide your DM response."
        ]        
        
        dm_completion = dm_brain.generate_content(
            dm_prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=DMResponseSchema,
            )
        )
                
        dm_data = json.loads(dm_completion.text)
        dm_text = dm_data.get("narrative", "")
        
        # 3. INTERCEPT AND AUTOMATE VIRTUAL DICE ROLLS
        if dm_data.get("requires_roll"):
            roll_type = dm_data.get("roll_type", "d20")
            reason = dm_data.get("roll_reason", "Action check")

            # Clean the string and default to addition
            clean_string = roll_type.replace(' ', '').lower()
            if not clean_string.startswith(('+', '-')):
                clean_string = '+' + clean_string

            total = 0
            # Break down every die and flat modifier
            matches = re.findall(r'([+-])(?:(\d*)d(\d+)|(\d+))', clean_string)
            
            for sign, qty, faces, flat in matches:
                multiplier = 1 if sign == '+' else -1
                
                if flat:
                    total += multiplier * int(flat)
                else:
                    qty = int(qty) if qty else 1
                    faces = int(faces)
                    for _ in range(qty):
                        total += multiplier * random.randint(1, faces)

            # Fallback just in case Mike sends gibberish
            if total == 0 and not matches:
                total = random.randint(1, 20)

            system_roll_log = f"\n\n[SYSTEM: Mike requested a {roll_type} for {reason}. Server rolled a {total}!]"
            dm_text += system_roll_log
        

        # --- DM LEDGER & SHEET UPDATES ---
        updates = dm_data.get("roster_updates", [])
        for update in updates:
            c_name = update.get("character_name", "").lower()
            if not c_name: continue
            
            sheet_path = os.path.join(CHARS_PATH, f"{c_name}.json")
            if os.path.exists(sheet_path):
                try:
                    with open(sheet_path, 'r', encoding='utf-8') as f:
                        c_data = json.load(f)
                    
                    c_data["xp"] = c_data.get("xp", 0) + update.get("xp_change", 0)
                    c_data["gold"] = c_data.get("gold", 0) + update.get("gold_change", 0)
                    
                    inv = c_data.get("inventory", [])
                    for item in update.get("inventory_add", []):
                        inv.append(item)
                    for item in update.get("inventory_remove", []):
                        if item in inv: inv.remove(item)
                    c_data["inventory"] = inv
                    
                    with open(sheet_path, 'w', encoding='utf-8') as f:
                        json.dump(c_data, f, indent=4)
                        
                    dm_text += f"\n\n[SYSTEM: {c_name.capitalize()}'s character sheet updated automatically.]"
                except Exception as e:
                    dm_text += f"\n\n[SYSTEM ERROR: Failed to update {c_name}'s sheet - {str(e)}]"

        # 4. DM IMAGE GENERATION
        img_html = ""
        if dm_data.get("generate_image") and dm_data.get("image_prompt"):
            try:
                art_style = "Dark fantasy RPG concept art, highly detailed, moody lighting: "
                img_res = image_engine.generate_content(
                    art_style + dm_data.get("image_prompt"),
                    generation_config={"response_modalities": ["IMAGE"]}
                )
                for part in img_res.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        fname = f"dm_vision_{uuid.uuid4().hex}.jpg"
                        with open(os.path.join(GEN_IMG_FOLDER, fname), 'wb') as f:
                            f.write(part.inline_data.data)
                        img_html = f'<br><img src="/gen_img/{fname}" style="max-width:100%; border-radius:8px; margin-top:10px; border: 1px solid #1a232c;">'
            except Exception as e:
                img_html = f"<br><i>[System: Mike tried to conjure an image, but failed: {str(e)}]</i>"
        
        dm_text += img_html
        final_responses.append(f"<b>Dungeon Master:</b><br>{dm_text}")
        
        turn_block = f"Brandon: {u_in}\nDM: {dm_data.get('narrative', '')} {system_roll_log if dm_data.get('requires_roll') else ''}\n"
        with open(BOOK_PATH, 'a', encoding='utf-8') as f:
            f.write(turn_block)
        history_context += turn_block

        # 5. PLAYER ROUTING
        moderator_instruction = """
        Analyze the DM's latest narrative statements and dice outcomes. Decide which of the AI players should react.
        Your output must be EXACTLY one of these choices, with no other text:
        - ERIC
        - LILLY
        - LYRA
        - PARTY
        """
        
        router_model = genai.GenerativeModel(model_name='gemini-2.5-pro', system_instruction=moderator_instruction)
        router_decision = router_model.generate_content(f"DM Latest Narrative:\n{dm_text}").text.strip().upper()

        agents_to_run = []
        if "PARTY" in router_decision:
            agents_to_run = ["Eric", "Lilly", "Lyra"]
        elif "ERIC" in router_decision:
            agents_to_run = ["Eric"]
        elif "LILLY" in router_decision:
            agents_to_run = ["Lilly"]
        else:
            agents_to_run = ["Lyra"]

       # Loop through the chosen player agents
        for agent_name in agents_to_run:
            persona_path = os.path.join(CHARS_PATH, f"{agent_name.lower()}_persona.txt")
            sheet_path = os.path.join(CHARS_PATH, f"{agent_name.lower()}.json")
            
            # Load the text persona
            if os.path.exists(persona_path):
                with open(persona_path, "r", encoding="utf-8") as f:
                    agent_instruction = f.read().strip()
            else:
                agent_instruction = f"You are {agent_name}, a player in this D&D campaign. Stay in character."

            # Load the character's specific JSON sheet
            if os.path.exists(sheet_path):
                with open(sheet_path, "r", encoding="utf-8") as f:
                    sheet_data = f.read()
                agent_instruction += f"\n\nHere is your exact Character Sheet. You MUST strictly abide by your known spells, weapons, and features:\n{sheet_data}"

            agent_instruction += f"\nYou are playing a tabletop campaign alongside Brandon and the others. React to the DM's narrative as {agent_name}."
            
            agent_brain = genai.GenerativeModel(model_name='gemini-2.5-flash', system_instruction=agent_instruction)
            
            # Fetch your specific Player's Handbook URI
            player_pdf = genai.get_file("files/m61uyxaidnit")
            
            # Feed the PDF and the history to the agent
            agent_prompt = [
                player_pdf,
                f"Campaign History:\n{history_context}\n\nTask: React directly to the DM's last move."
            ]
            
            response = agent_brain.generate_content(agent_prompt)
            reply = response.text
            
            final_responses.append(f"<b>{agent_name}:</b><br>{reply}")
            
            agent_block = f"{agent_name}: {reply}\n"
            with open(BOOK_PATH, 'a', encoding='utf-8') as f:
                f.write(agent_block)
            history_context += agent_block

        # Return JSON instead of raw HTML so the frontend can read the turn state
        return jsonify({
            "html": "<br><br>".join(final_responses),
            "whose_turn": dm_data.get("whose_turn", "Brandon"),
            "combat_active": dm_data.get("combat_active", False)
        })

    except Exception as e:
        # Return JSON instead of raw HTML so the frontend can read the turn state
        return jsonify({
            "html": f"<b>System Error:</b> {str(e)}",
            "whose_turn": "Brandon",
            "combat_active": False
        })

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files: return "No file"
    file = request.files['file']
    if file.filename == '': return "No filename"
    save_path = os.path.join(GEN_IMG_FOLDER, file.filename)
    file.save(save_path)
    return f"File {file.filename} uploaded."

@app.route('/agent_chat', methods=['POST'])
def agent_chat():
    try:
        history_context = ""
        if os.path.exists(BOOK_PATH):
            with open(BOOK_PATH, 'r', encoding='utf-8') as f:
                history_context = f.read()[-50000:]
        
        final_responses = []
        # Randomize who speaks first in the banter
        agents_to_run = ["Eric", "Lilly", "Lyra"]
        random.shuffle(agents_to_run)
        
        for agent_name in agents_to_run:
            persona_path = os.path.join(CHARS_PATH, f"{agent_name.lower()}_persona.txt")
            if os.path.exists(persona_path):
                with open(persona_path, "r", encoding="utf-8") as f:
                    agent_instruction = f.read().strip()
            else:
                agent_instruction = f"You are {agent_name}."

            agent_brain = genai.GenerativeModel(model_name='gemini-2.5-flash', system_instruction=agent_instruction)
            prompt = f"Campaign History:\n{history_context}\n\nTask: Banter with the party about our current predicament. Do not advance the plot. Keep it short, in character, and react to the last thing said."
            
            response = agent_brain.generate_content(prompt)
            reply = response.text
            
            final_responses.append(f"<b>{agent_name}:</b><br>{reply}")
            
            # Save to history so the next agent in the loop hears it
            agent_block = f"{agent_name}: {reply}\n"
            with open(BOOK_PATH, 'a', encoding='utf-8') as f:
                f.write(agent_block)
            history_context += agent_block
            
        return "<br><br>".join(final_responses)
    except Exception as e:
        return f"Banter Error: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=2627)
